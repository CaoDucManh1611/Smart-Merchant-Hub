from copy import deepcopy
from unittest.mock import patch
import pytest
from test_business_request import setup
from app.schemas.business_profile import CollectionField
from app.services.business_profile import get_business_profile,save_business_profile
from app.services.business_request import advance_business_request
from app.services.conversation_graph import graph_reply
from app.models.customer_collection import CustomerCollectionSession
from app.models.sales import Order


@pytest.mark.parametrize('messages', [
    ['Ngô Long Thiên','0900000011','test@example.com','123 Nguyễn Huệ, Quận 1, TP HCM','cod'],
    ['Tên người nhận: Ngô Long Thiên\nSố điện thoại: 0900000011\nEmail: test@example.com\nĐịa chỉ nhận hàng: 123 Nguyễn Huệ, Quận 1, TP HCM\nThanh toán (COD/chuyển khoản): COD'],
    ['cod','Ngô Long Thiên\n0900000011','Email: test@example.com\nĐịa chỉ nhận hàng: 123 Nguyễn Huệ, Quận 1, TP HCM'],
])
def test_form_merges_fragments_and_cod_without_ai(setup,messages):
    db,conversation,product,*_=setup
    profile=get_business_profile(db,1)
    profile.payment_methods=['cod','bank_transfer']
    for field in [CollectionField(key='email',label='Email'),CollectionField(key='address',label='Địa chỉ nhận hàng')]:
        if not any(existing.key == field.key for existing in profile.collection_fields['goods']):
            profile.collection_fields['goods'].append(field)
    save_business_profile(db,1,profile);db.commit()
    action={'action':'collect','action_evidence':'mua 2','offering_ref':f'product:{product.id}',
            'fields':{'quantity':{'value':'2','evidence':'2'}}}
    advance_business_request(db,business_id=1,conversation=conversation,query='mua 2',history=[],job_key='form-start',_interpreted_action=action)
    with patch('app.services.conversation_graph.call_llm',side_effect=AssertionError('form needs no AI')), \
         patch('app.services.business_request.call_llm',side_effect=AssertionError('COD needs no AI')):
        for index,message in enumerate(messages):
            reply=graph_reply(db,business_id=1,conversation=conversation,query=message,job_key=f'form-{index}')
            assert 'gặp lỗi' not in reply.prompt
    session=db.query(CustomerCollectionSession).filter_by(conversation_id=conversation.id,purpose='business_request').one()
    values=session.collected_fields['values']
    assert values['name']=='Ngô Long Thiên'
    assert values['phone']=='đã cung cấp'
    assert values['email']=='test@example.com'
    assert values['address']=='123 Nguyễn Huệ, Quận 1, TP HCM'
    assert values['payment_method']=='cod'
    assert session.collected_fields['phase']=='review'
    assert db.query(Order).count()==0
    with patch('app.services.business_request.call_llm',side_effect=AssertionError('confirmation needs no AI')), \
         patch('app.services.conversation_graph.call_llm',side_effect=AssertionError('confirmation needs no AI')):
        graph_reply(db,business_id=1,conversation=conversation,query='xác nhận tạo đơn',job_key='form-confirm')
    order=db.query(Order).one()
    assert order.shipping_address=='123 Nguyễn Huệ, Quận 1, TP HCM'
    assert order.metadata_['payment_method']=='cod'


def test_form_lists_all_fields_marks_received_and_does_not_submit(setup):
    from app.services.order_collection_form import render_order_form,order_form_action
    workflow={'received':{'name':'Khách Thử'},'field_definitions':[{'key':k} for k in ['name','phone','email','address']],
        'configured_payment_methods':{'cod':'COD','bank_transfer':'Chuyển khoản'}}
    text=render_order_form(workflow)
    assert 'Tên người nhận: đã ghi nhận' in text
    assert 'Email:' in text and 'Địa chỉ nhận hàng:' in text
    assert 'Thanh toán (COD/chuyển khoản):' in text
    fields={'offering_ref':'product:1','values':{},'field_definitions':[{'key':'name'}]}
    assert order_form_action('xác nhận tạo đơn',fields)['action']=='collect'
    assert order_form_action('xác nhận tạo đơn',{**fields,'phase':'review'})['action']=='submit'
    assert order_form_action('giá bao nhiêu?',fields) is None


@pytest.mark.parametrize('messages',[
 ['Khách Kiểm Tra\n0900000011\ntest@example.com\n144 LTT\nChuyển Khoản'],
 ['Khách Kiểm Tra','0900000011','test@example.com','144 LTT','Chuyển Khoản'],
])
def test_short_shipping_address_and_complete_form_never_require_ai(setup,messages):
    db,c,p,*_=setup
    action={'action':'collect','action_evidence':'mua 2','offering_ref':f'product:{p.id}',
            'fields':{'quantity':{'value':'2','evidence':'2'}}}
    advance_business_request(db,business_id=1,conversation=c,query='mua 2',history=[],job_key='short-form-start',_interpreted_action=action)
    with patch('app.services.conversation_graph.call_llm',side_effect=AssertionError('No AI for form')),patch('app.services.business_request.call_llm',side_effect=AssertionError('No AI for form')):
        for i,message in enumerate(messages):
            reply=graph_reply(db,business_id=1,conversation=c,query=message,job_key=f'short-form-{i}')
    session=db.query(CustomerCollectionSession).filter_by(conversation_id=c.id).one()
    values=session.collected_fields['values']
    assert values['address']=='144 LTT' and values['name']=='Khách Kiểm Tra'
    assert values['email']=='test@example.com' and values['phone']=='đã cung cấp'
    assert values['payment_method']=='bank_transfer' and values['quantity']==2
    assert session.collected_fields['phase']=='review'
    assert '144 LTT' in reply.prompt and db.query(Order).count()==0
