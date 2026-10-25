from decimal import Decimal
import pytest
from fastapi import HTTPException
from test_business_request import setup,run,details
from test_order_payment_request import configured,paid
from app.models import Customer,Conversation
from app.models.sales import Order
from app.models.customer_collection import CustomerCollectionSession,CustomerContact
from app.services.customer_collection import normalize_contact
from app.services.customer_merge_service import duplicate_evidence,find_duplicate_suggestions,merge_customer,undo_customer_merge
from app.services.customer_order_service import customer_context_reply
from app.services.order_service import transition_sales_order,SalesOrderOperationError


def book(data,phone='0901234567',key='one'):
    ref=f'product:{data[2].id}'
    text,values=details('goods')
    text=text.replace('0901234567',phone)
    values['phone']={'value':phone,'evidence':phone}
    run(data,'collect',ref,text,values,key=key+'-collect')
    result=run(data,'submit',ref,'Đồng ý gửi yêu cầu',key=key+'-submit')
    return result,data[0].query(Order).filter_by(conversation_id=data[1].id).one()


def pair(data):
    db=data[0];configured(db)
    data[1].customer.name='Khách Thử Nghiệm'
    first_result,first_order=book(data,key='first')
    other=Customer(business_id=1,channel='telegram',external_user_id='merge-test-only',name='Khách Thử Nghiệm')
    db.add(other);db.flush()
    conv=Conversation(business_id=1,customer_id=other.id,channel='telegram');db.add(conv);db.commit()
    other_data=(db,conv,*data[2:])
    second_result,second_order=book(other_data,key='second')
    return other,conv,first_order,second_order,second_result


def test_contact_collected_twice_is_suggested_without_stealing_contact_or_auto_merge(setup):
    db,conv,*_=setup
    other,other_conv,first_order,second_order,result=pair(setup)
    assert result['state']=='submitted'
    assert second_order.shipping_phone==normalize_contact('phone','0901234567')
    evidence=duplicate_evidence(db,conv.customer,other)
    assert 'phone' in evidence['matched_fields']
    assert any(row['source_customer_id']==other.id for row in find_duplicate_suggestions(db,1,customer_id=conv.customer_id))
    assert other.status!='merged' and other_conv.customer_id==other.id
    assert db.query(CustomerContact).one().customer_id==conv.customer_id
    assert 'chưa tìm thấy' in customer_context_reply(db,1,other_conv.id,f'Cho mình QR đơn {first_order.order_number}').lower()
    assert '0901234567' not in str(db.query(CustomerCollectionSession).filter_by(customer_id=other.id).one().collected_fields)


def test_merge_and_undo_preserve_request_payment_ownership(setup):
    db,conv,*_=setup
    other,other_conv,first_order,second_order,result=pair(setup)
    other_id=other.id;main_id=conv.customer_id
    merge=merge_customer(db,main_id,other_id,1,reason='Isolated test')
    db.expire_all()
    session=db.query(CustomerCollectionSession).filter_by(conversation_id=other_conv.id).one()
    assert other_conv.customer_id==main_id and second_order.customer_id==main_id
    assert session.customer_id==main_id
    answer=customer_context_reply(db,1,other_conv.id,'Cho mình QR chuyển khoản')
    assert second_order.order_number in answer and 'amount=450000' in answer
    assert first_order.order_number not in answer
    customer_context_reply(db,1,other_conv.id,'Tôi đã chuyển khoản rồi')
    assert second_order.paid_amount==0
    with pytest.raises(SalesOrderOperationError):transition_sales_order(db,order_id=second_order.id,to_status='confirmed',actor_id=None,business_id=1)
    undo_customer_merge(db,merge.id,1);db.expire_all()
    assert other_conv.customer_id==other_id and second_order.customer_id==other_id and session.customer_id==other_id
    assert second_order.order_number in customer_context_reply(db,1,other_conv.id,'Cho mình QR chuyển khoản')
    paid(db,second_order);db.commit()
    transition_sales_order(db,order_id=second_order.id,to_status='confirmed',actor_id=None,business_id=1)
    assert second_order.status=='confirmed' and first_order.paid_amount==0


def test_merge_never_crosses_business_boundary(setup):
    db,conv,*_=setup
    other=Customer(business_id=2,channel='telegram',external_user_id='foreign-merge',phone='0901234567')
    db.add(other);db.commit()
    with pytest.raises(HTTPException):merge_customer(db,conv.customer_id,other.id,1)


def test_merge_moves_encrypted_contact_and_restores_primary_on_undo(setup):
    db,conv,*_=setup;configured(db)
    _,order=book(setup,key='main')
    source=Customer(business_id=1,channel='telegram',external_user_id='other-contact',name='TEST source');db.add(source);db.flush()
    source_conv=Conversation(business_id=1,customer_id=source.id,channel='telegram');db.add(source_conv);db.commit()
    _,source_order=book((db,source_conv,*setup[2:]),phone='0907654321',key='source')
    contact=db.query(CustomerContact).filter_by(customer_id=source.id).one()
    assert contact.is_primary
    merge=merge_customer(db,conv.customer_id,source.id,1)
    assert contact.customer_id==conv.customer_id and not contact.is_primary
    undo_customer_merge(db,merge.id,1);db.expire_all()
    assert contact.customer_id==source.id and contact.is_primary
    assert source_order.customer_id==source.id


def test_changed_phone_requires_new_review_even_when_submit_requested(setup):
    db,conv,*_=setup;configured(db);ref=f'product:{setup[2].id}'
    text,values=details('goods');run(setup,'collect',ref,text,values)
    result=run(setup,'submit',ref,'Đồng ý nhưng đổi số thành 0907654321',{'phone':{'value':'0907654321','evidence':'0907654321'}})
    assert result['state']=='review' and db.query(Order).count()==0
    _,order=book(setup,phone='0907654321',key='corrected')
    assert order.shipping_phone==normalize_contact('phone','0907654321')


def test_email_alone_and_international_phone_format_are_review_candidates(setup):
    db,conv,*_=setup
    main=conv.customer;main.email='TEST@example.invalid';main.phone='0901234567'
    other=Customer(business_id=1,channel='telegram',external_user_id='email-only',email='test@example.invalid',phone='+84901234567')
    db.add(other);db.commit()
    evidence=duplicate_evidence(db,main,other)
    assert {'email','phone'}.issubset(evidence['matched_fields'])
    other.phone=None;main.phone=None;db.commit()
    assert any(r['source_customer_id']==other.id for r in find_duplicate_suggestions(db,1,customer_id=main.id))
    assert other.status!='merged'


def test_payment_method_is_not_requested_before_customer_details(setup):
    db=setup[0];configured(db)
    result=run(setup,'collect',f'product:{setup[2].id}','Tôi muốn đặt hàng')
    assert result['state']=='collecting' and result['payment_methods']=={}
    assert 'Hình thức thanh toán' not in result['missing']
    assert all(d['key']!='payment_method' for d in result['field_definitions'])


def test_next_message_uses_survivor_identity_and_undo_restores_it(setup):
    from app.models.customer_identity import CustomerIdentity
    from app.services.customer_identity import resolve_customer,resolve_conversation_recipient
    db,conv,*_=setup
    other,other_conv,first_order,second_order,_=pair(setup)
    db.add(CustomerIdentity(business_id=1,customer_id=other.id,channel='telegram',external_account_id='TEST-PAGE',external_user_id='merge-test-only'));db.commit()
    source_id=other.id
    merge=merge_customer(db,conv.customer_id,source_id,1);db.expire_all()
    resolved=resolve_customer(db,1,'telegram','merge-test-only','TEST-PAGE')
    assert resolved.id==conv.customer_id
    assert resolve_conversation_recipient(db,conversation_id=other_conv.id,business_id=1)[1]=='merge-test-only'
    undo_customer_merge(db,merge.id,1);db.expire_all()
    assert resolve_customer(db,1,'telegram','merge-test-only','TEST-PAGE').id==source_id
