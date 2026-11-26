import pytest
from unittest.mock import patch
from test_business_request import setup
from app.models.customer_collection import CustomerCollectionSession
from app.models.sales import Order
from app.services.customer_collection_flow import advance_customer_collection


def test_named_product_followed_by_loai_nay_gia_the_nao_is_not_category_question(setup):
    from app.services.conversation_graph import graph_reply
    db,conversation,product,*_=setup
    product.name='Sữa rửa mặt dịu nhẹ – Tiêu chuẩn'
    product.description='Dữ liệu giả lập: cần đối chiếu cách dùng'
    db.commit()
    with patch('app.services.conversation_graph.call_llm',side_effect=AssertionError('catalog fact should need no AI')):
        result=graph_reply(db,business_id=1,conversation=conversation,
            query='Mình đang xem Sữa rửa mặt dịu nhẹ – Tiêu chuẩn. Loại này giá thế nào, còn bao nhiêu và dùng ra sao?',job_key='named-product-detail')
    assert product.name in result.prompt
    assert '200.000' in result.prompt
    assert 'chưa xác nhận công dụng' in result.prompt


def test_positional_email_address_and_payment_in_same_turn():
    from app.services.customer_collection_flow import _parse_order_form_details
    values,found,invalid=_parse_order_form_details(
        'buyer@example.com\nE13/15/1N\nMình chọn chuyển khoản nhé',
        ['name','phone','email','address','payment_method'],fallback_field='email')
    assert found and not invalid
    assert values['email']=='buyer@example.com'
    assert values['address']=='E13/15/1N'
    assert values['payment_method']=='bank_transfer'


def test_conversational_address_keeps_only_delivery_value():
    from app.services.customer_collection_flow import _parse_order_form_details
    values,_,_=_parse_order_form_details('Địa chỉ của mình là E13/15/1N nhé.',
        ['name','phone','email','address','payment_method'],fallback_field='address')
    assert values['address']=='E13/15/1N'


@pytest.mark.parametrize('status', ['confirmed','pending_confirmation','completed','draft'])
def test_separate_purchase_releases_old_confirmation_without_changing_order(setup,status):
    db,conversation,product,*_=setup
    order=Order(business_id=1,customer_id=conversation.customer_id,conversation_id=conversation.id,
        order_number='OLD-CHECKOUT',status=status,total_amount=200000)
    db.add(order);db.flush()
    session=CustomerCollectionSession(business_id=1,customer_id=conversation.customer_id,
        conversation_id=conversation.id,purpose='order',source_channel=conversation.channel,
        required_fields=['name','phone','address','payment_method'],status='completed',
        collected_fields={'draft_order_id':order.id,'awaiting_customer_confirmation':True,
                          'product_id':product.id,'quantity':1})
    db.add(session);db.commit()
    result=advance_customer_collection(db,business_id=1,customer_id=conversation.customer_id,
        conversation_id=conversation.id,source_channel=conversation.channel,
        text='Tôi muốn mua 1 sản phẩm, làm đơn mới riêng giúp mình nhé')
    assert result is None
    assert session.collected_fields['awaiting_customer_confirmation'] is False
    assert order.status==status
