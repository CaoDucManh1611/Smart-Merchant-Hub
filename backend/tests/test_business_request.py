import json
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from pydantic import ValidationError
from app.database.bases import TenantBase
from app.models import Business,Customer,Conversation
from app.models.sales import Product,Order
from app.models.industry_modules import AppointmentService,Appointment
from app.models.customer_collection import CustomerCollectionSession
from app.schemas.business_profile import BusinessProfile
from app.services.business_profile import get_business_profile,save_business_profile
from app.services.business_request import advance_business_request,current_offerings


@pytest.fixture
def setup():
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False})
    Business.metadata.create_all(engine);TenantBase.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Business(id=1,name='Test A',slug='test-a'),Business(id=2,name='Test B',slug='test-b')]);db.flush()
        c=Customer(business_id=1,channel='facebook',external_user_id='synthetic');db.add(c);db.flush()
        conversation=Conversation(business_id=1,customer_id=c.id,channel='facebook');db.add(conversation)
        goods=Product(business_id=1,name='Hàng thử',sku='TEST-GOODS',price=200000,stock_quantity=10,metadata_={'offering_type':'goods','billing_unit':'chiếc'})
        rental=Product(business_id=1,name='Máy ảnh thử',sku='TEST-RENT',price=100000,stock_quantity=1,metadata_={'offering_type':'rental','billing_unit':'ngày'})
        foreign=Product(business_id=2,name='Không được đọc',sku='PRIVATE',price=999,stock_quantity=1)
        service=AppointmentService(business_id=1,name='Dịch vụ thử',price=150000,duration_minutes=30)
        db.add_all([goods,rental,foreign,service]);db.commit()
        from app.tenancy.workspace_modules import save_workspace_config
        save_workspace_config(db,1,{'business_type':'mixed','enabled_modules':['retail','appointments']});db.commit()
        with patch('app.services.business_request.record_quota_usage'):
            yield db,conversation,goods,rental,service,foreign
    engine.dispose()


def run(setup,action,ref,text,fields=None,key=None):
    db,conversation,*_=setup
    payload={'action':action,'action_evidence':text,'offering_ref':ref,'fields':fields or {}}
    with patch('app.services.business_request.call_llm',return_value=json.dumps(payload,ensure_ascii=False)):
        return advance_business_request(db,business_id=1,conversation=conversation,query=text,history=[],job_key=key or text)


def field(value,evidence=None): return {'value':value,'evidence':evidence or str(value)}


def details(kind):
    values={'name':field('Khách Thử Nghiệm'),'phone':field('0901234567'),'payment_method':field('bank_transfer','chuyển khoản')}
    if kind=='goods': values['quantity']=field('2')
    elif kind=='rental': values['start_date']=field('2099-11-01','01/11/2099')
    else: values['starts_at']=field('2099-11-01T09:00:00+07:00','01/11/2099 09:00')
    text='Khách Thử Nghiệm, 0901234567, '+('2 chiếc' if kind=='goods' else '01/11/2099 09:00')
    return text+', chuyển khoản',values


@pytest.mark.parametrize('kind',['goods','rental','service'])
def test_three_business_types_collect_review_then_submit(setup,kind):
    db,_,goods,rental,service,_=setup
    entity={'goods':goods,'rental':rental,'service':service}[kind]
    ref=f"{'service' if kind=='service' else 'product'}:{entity.id}"
    text,values=details(kind)
    first=run(setup,'collect',ref,text,values)
    assert first['state']=='review' and not first['order_created']
    assert db.query(Order).count()==0 and db.query(Appointment).count()==0
    session=db.query(CustomerCollectionSession).one()
    assert '0901234567' not in str(session.collected_fields)
    result=run(setup,'submit',ref,'Xác nhận gửi yêu cầu',key='approve')
    assert result['state']=='submitted'
    if kind=='service':
        appointment=db.query(Appointment).one()
        assert appointment.status=='pending' and not appointment.send_customer_reminder
        assert db.query(Order).one().metadata_['appointment_id']==appointment.id
    else:
        order=db.query(Order).one()
        assert order.status=='draft' and order.paid_amount==0
        assert order.total_amount==(400000 if kind=='goods' else 100000)
        assert order.metadata_['billing_unit']==('chiếc' if kind=='goods' else 'ngày')
        assert order.shipping_phone=='+84901234567'
    with patch('app.services.business_request.call_llm') as model:
        repeated=advance_business_request(db,business_id=1,conversation=setup[1],query='Xác nhận gửi yêu cầu',history=[],job_key='approve')
    assert repeated==result
    model.assert_not_called()


def test_price_update_requires_new_approval_and_uses_live_price(setup):
    db,_,goods,*_=setup;ref=f'product:{goods.id}'
    text,values=details('goods');run(setup,'collect',ref,text,values)
    goods.price=250000;db.commit()
    result=run(setup,'submit',ref,'Gửi yêu cầu',key='price-changed')
    assert result['state']=='review' and 'Giá đã thay đổi' in result['instruction']
    assert db.query(Order).count()==0
    result=run(setup,'submit',ref,'Đồng ý giá mới, gửi yêu cầu',key='approve-new')
    assert result['order_created'] and db.query(Order).one().total_amount==500000


def test_changed_details_do_not_reuse_previous_approval(setup):
    db,_,goods,*_=setup;ref=f'product:{goods.id}'
    text,values=details('goods');run(setup,'collect',ref,text,values)
    result=run(setup,'submit',ref,'Đồng ý nhưng đổi thành 3 chiếc',{'quantity':field('3')})
    assert result['state']=='review' and db.query(Order).count()==0


def test_stock_change_prevents_creation(setup):
    db,_,goods,*_=setup;ref=f'product:{goods.id}'
    text,values=details('goods');run(setup,'collect',ref,text,values)
    goods.stock_quantity=0;db.commit()
    assert run(setup,'submit',ref,'Xác nhận gửi')['state']=='unavailable'
    assert db.query(Order).count()==0


def test_foreign_shop_offering_is_never_resolved(setup):
    db,_,_,_,_,foreign=setup
    result=run(setup,'collect',f'product:{foreign.id}','Tôi muốn đặt hàng')
    assert result['state']=='clarify_offering'
    assert db.query(CustomerCollectionSession).count()==0
    assert foreign.name not in str(current_offerings(db,1))


def test_unproved_fields_and_invented_dates_are_not_saved(setup):
    db,_,_,rental,*_=setup;ref=f'product:{rental.id}'
    result=run(setup,'collect',ref,'Có 2 người ở',{
        'name':field('Bịa Tên','Không có trong câu khách'),
        'start_date':field('2099-11-01','2'),
        'draft_order_id':field('123','2')})
    assert result['state']=='collecting'
    assert db.query(CustomerCollectionSession).one().collected_fields['values']=={}


def test_past_date_can_be_configured_for_non_booking_information(setup):
    db,_,goods,*_=setup
    data=BusinessProfile().model_dump();data['collection_fields']['goods']=[{'key':'purchased_on','label':'Ngày mua cũ','type':'date','future_only':False}]
    profile=BusinessProfile.model_validate(data)
    save_business_profile(db,1,profile.model_dump());db.commit()
    result=run(setup,'collect',f'product:{goods.id}','Ngày mua cũ 01/11/2020',{'purchased_on':field('2020-11-01','01/11/2020')})
    assert result['state']=='collecting' and result['missing']==['Hình thức thanh toán']


def test_question_and_cancellation_do_not_create_orders(setup):
    db,_,goods,*_=setup;ref=f'product:{goods.id}'
    run(setup,'collect',ref,'Tôi muốn đặt hàng')
    before=dict(db.query(CustomerCollectionSession).one().collected_fields)
    assert run(setup,'question',ref,'Có bảo hành không?')['state']=='question'
    assert db.query(CustomerCollectionSession).one().collected_fields==before
    assert run(setup,'cancel',ref,'Dừng yêu cầu này')['state']=='cancelled'
    assert db.query(CustomerCollectionSession).one().status=='cancelled'
    assert db.query(Order).count()==0


def test_service_conflict_does_not_make_another_appointment(setup):
    db,conversation,_,_,service,_=setup;ref=f'service:{service.id}'
    text,values=details('service');run(setup,'collect',ref,text,values)
    starts=datetime(2099,11,1,2)
    db.add(Appointment(business_id=1,customer_id=conversation.customer_id,service_id=service.id,
        starts_at=starts,ends_at=starts+timedelta(minutes=30),status='scheduled'));db.commit()
    assert run(setup,'submit',ref,'Xác nhận gửi')['state']=='schedule_conflict'
    assert db.query(Appointment).count()==1


def test_profile_is_tenant_scoped_and_rejects_reserved_fields(setup):
    db,*_=setup
    data=BusinessProfile(default_offering_type='rental',default_billing_unit='ngày').model_dump()
    save_business_profile(db,1,data);db.commit()
    assert get_business_profile(db,2).default_offering_type=='goods'
    data['collection_fields']['rental']=[{'key':'draft_order_id','label':'Bad','type':'text'}]
    with pytest.raises(ValidationError): BusinessProfile.model_validate(data)


def test_switching_business_type_resets_field_definitions(setup):
    db,_,goods,_,service,_=setup
    text,values=details('goods');run(setup,'collect',f'product:{goods.id}',text,values)
    result=run(setup,'collect',f'service:{service.id}','Đổi sang dịch vụ thử')
    assert result['state']=='collecting'
    fields=db.query(CustomerCollectionSession).one().collected_fields
    assert fields['values']=={}
    assert 'starts_at' in [item['key'] for item in fields['field_definitions']]
    assert 'quantity' not in [item['key'] for item in fields['field_definitions']]


def test_staff_can_accept_or_decline_pending_service_request():
    from app.api.appointments import _validate_status_transition
    from fastapi import HTTPException
    for status in ('scheduled','confirmed','cancelled'):
        _validate_status_transition('pending',status)
    with pytest.raises(HTTPException): _validate_status_transition('pending','completed')


def test_disabled_appointment_module_cannot_accept_hidden_services(setup):
    db,_,_,_,service,_=setup
    from app.tenancy.workspace_modules import save_workspace_config
    save_workspace_config(db,1,{'business_type':'retail','enabled_modules':['retail']});db.commit()
    assert f'service:{service.id}' not in [o['ref'] for o in current_offerings(db,1)]
    assert run(setup,'collect',f'service:{service.id}','Đặt dịch vụ này')['state']=='clarify_offering'


def test_payment_question_uses_current_submitted_request_not_cancelled_orders(setup):
    db,conversation,goods,*_=setup
    text,values=details('goods');run(setup,'collect',f'product:{goods.id}',text,values)
    result=run(setup,'submit',f'product:{goods.id}','Xác nhận gửi',key='payment-submit')
    db.add(Order(business_id=1,customer_id=conversation.customer_id,conversation_id=conversation.id,order_number='OLD-CANCELLED',status='cancelled',total_amount=100000));db.commit()
    from app.services.customer_order_service import customer_context_reply
    answer=customer_context_reply(db,1,conversation.id,'Tôi muốn thanh toán thì sao')
    assert result['order_number'] in answer and 'bảng kê khoản thu' in answer and '400.000' in answer
    assert 'OLD-CANCELLED' not in answer
    assert 'không cần thanh toán' in customer_context_reply(db,1,conversation.id,'thanh toán đơn OLD-CANCELLED')


def test_current_transfer_configuration_is_available_to_policy_answers(setup):
    db,conversation,*_=setup
    from app.models.business_setting import BusinessSetting
    from app.services.conversation_graph import graph_reply
    db.add(BusinessSetting(business_id=1,key='shop.bank_transfer.enabled',value='true'));db.commit()
    with patch('app.services.conversation_graph.call_llm',side_effect=[
        '{"mode":"answer","tools":["knowledge"]}',
        '{"answer":"Shop có hỗ trợ chuyển khoản ngân hàng.","sources":[1]}']) as model, \
         patch('app.services.quota_service.record_quota_usage'), \
         patch('app.rag.retriever.retrieve',return_value=[]):
        result=graph_reply(db,business_id=1,conversation=conversation,query='Shop có hỗ trợ chuyển khoản không?',job_key='payment-method')
    assert 'chuyển khoản ngân hàng' in result.prompt
    assert 'Shop đã bật chuyển khoản ngân hàng' in model.call_args.args[0][-1]['content']


def test_customer_details_then_payment_choice_then_explicit_confirmation(setup):
    db,_,goods,*_=setup;ref=f'product:{goods.id}'
    text,values=details('goods');values.pop('payment_method');text=text.replace(', chuyển khoản','')
    result=run(setup,'collect',ref,text,values)
    assert result['state']=='collecting' and result['missing']==['Hình thức thanh toán']
    assert db.query(CustomerCollectionSession).one().current_field=='payment_method'
    assert not db.query(Order).count()
    assert run(setup,'submit',ref,'Đồng ý gửi luôn')['state']=='collecting'
    result=run(setup,'collect',ref,'Mình chọn chuyển khoản',{'payment_method':field('bank_transfer','chuyển khoản')})
    assert result['state']=='review' and not db.query(Order).count()
    result=run(setup,'submit',ref,'Đúng rồi, gửi yêu cầu giúp mình')
    order=db.query(Order).one()
    assert result['order_created'] and order.metadata_['payment_method']=='bank_transfer'
    assert order.paid_amount==0 and order.status=='draft'


def test_payment_method_must_be_enabled_and_correction_requires_review(setup):
    db,_,goods,*_=setup;ref=f'product:{goods.id}'
    text,values=details('goods');values.pop('payment_method');text=text.replace(', chuyển khoản','')
    run(setup,'collect',ref,text,values)
    result=run(setup,'collect',ref,'Tôi chọn COD',{'payment_method':field('cod','COD')})
    assert result['state']=='collecting' and 'Hình thức thanh toán' in result['invalid']
    result=run(setup,'collect',ref,'Trả tiền mặt',{'payment_method':field('cash','tiền mặt')})
    assert result['state']=='review'
    result=run(setup,'submit',ref,'Đồng ý nhưng đổi sang chuyển khoản',{'payment_method':field('bank_transfer','chuyển khoản')})
    assert result['state']=='review' and not db.query(Order).count()


def test_review_shows_all_validated_fields_including_payment_and_date(setup):
    db,conversation,_,rental,*_=setup
    text,values=details('rental')
    review=run(setup,'collect',f'product:{rental.id}',text,values)
    from app.services.conversation_graph import graph_reply
    with patch('app.services.conversation_graph.call_llm',return_value='{"mode":"workflow","tools":[]}'), \
         patch('app.services.quota_service.record_quota_usage'), \
         patch('app.services.business_request.advance_business_request',return_value=review):
        answer=graph_reply(db,business_id=1,conversation=conversation,query='Chọn chuyển khoản',job_key='full-review').prompt
    for value in ('Khách Thử Nghiệm','Số liên hệ: đã cung cấp','01/11/2099','Chuyển khoản','100.000','ngày','xác nhận gửi'):
        assert value in answer


def test_invalid_correction_cannot_submit_previous_values(setup):
    db,_,goods,*_=setup;ref=f'product:{goods.id}'
    text,values=details('goods');run(setup,'collect',ref,text,values)
    result=run(setup,'submit',ref,'Đồng ý, đổi số lượng 0',{'quantity':field('0')})
    assert result['state']=='collecting' and result['invalid']==['Số lượng']
    assert db.query(Order).count()==0


def test_qr_for_open_request_does_not_select_an_older_order(setup):
    db,conversation,goods,*_=setup
    text,values=details('goods');run(setup,'collect',f'product:{goods.id}',text,values)
    db.add(Order(business_id=1,customer_id=conversation.customer_id,conversation_id=conversation.id,order_number='OLD-DRAFT',status='draft',total_amount=100000));db.commit()
    from app.services.customer_order_service import customer_context_reply
    answer=customer_context_reply(db,1,conversation.id,'Đâu mã QR để tôi ck')
    assert 'đang soạn' in answer and 'chưa có đơn' in answer
    assert 'OLD-DRAFT' not in answer


def test_planned_workflow_rechecks_conflicting_question_interpretation(setup):
    db,conversation,goods,*_=setup
    run(setup,'collect',f'product:{goods.id}','Tôi muốn đặt hàng')
    text,values=details('goods')
    payload={'action':'collect','action_evidence':text,'offering_ref':f'product:{goods.id}','fields':values}
    with patch('app.services.business_request.call_llm',side_effect=[json.dumps({'action':'question','fields':{}}),json.dumps(payload)]) as llm:
        result=advance_business_request(db,business_id=1,conversation=conversation,query=text,history=[{'role':'user','content':'QR gửi lúc nào?'}],job_key='conflict-recheck',workflow_planned=True)
    assert llm.call_count==2 and result['state']=='review'
    assert result['received']['name']=='Khách Thử Nghiệm'
    assert db.query(CustomerCollectionSession).one().collected_fields['values']['payment_method']=='bank_transfer'


def test_recheck_preserves_genuine_question_without_saving_fields(setup):
    db,conversation,goods,*_=setup
    run(setup,'collect',f'product:{goods.id}','Tôi muốn đặt hàng')
    with patch('app.services.business_request.call_llm',return_value=json.dumps({'action':'question'})):
        result=advance_business_request(db,business_id=1,conversation=conversation,query='Chính sách bảo hành ra sao?',history=[],job_key='true-question',workflow_planned=True)
    assert result['state']=='question' and db.query(Order).count()==0
    assert db.query(CustomerCollectionSession).one().collected_fields['values']=={}
