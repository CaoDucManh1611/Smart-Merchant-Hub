from unittest.mock import patch
import pytest
from test_business_request import setup
from app.models.sales import Order
from app.models.ticket import Ticket
from app.models.notification import Notification
from app.models.customer_collection import CustomerCollectionSession
from app.services.conversation_graph import graph_reply
from app.services.customer_return_intake import customer_return_reply


@pytest.mark.parametrize('phrase',['Tôi muốn hoàn đơn','Mình đã nhận hàng rồi nhưng muốn hoàn lại đơn, shop hỗ trợ giúp mình nhé.','Tôi muốn trả lại hàng'])
def test_return_asks_explicit_code_then_hands_off_without_money_or_state_change(setup,phrase):
    db,conversation,*_=setup
    order=Order(business_id=1,customer_id=conversation.customer_id,conversation_id=conversation.id,
        order_number='CHAT-900',status='delivered',total_amount=200000,paid_amount=200000,refunded_amount=0)
    db.add(order);db.commit()
    with patch('app.services.conversation_graph.call_llm',side_effect=AssertionError('return intake needs no model')):
        first=graph_reply(db,business_id=1,conversation=conversation,query=phrase,job_key='return-start')
        assert 'gửi mã đơn' in first.prompt
        assert db.query(Ticket).count()==0
        wrong=graph_reply(db,business_id=1,conversation=conversation,query='CHAT-999999',job_key='return-wrong')
        assert 'chưa tìm thấy' in wrong.prompt
        assert db.query(Ticket).count()==0
        second=graph_reply(db,business_id=1,conversation=conversation,query='mã đơn CHAT-900',job_key='return-number')
        assert 'đã nhận thông tin hoàn đơn CHAT-900' in second.prompt
        assert 'đợi nhân viên' in second.prompt
        repeated=graph_reply(db,business_id=1,conversation=conversation,query='CHAT-900',job_key='return-repeat')
        assert 'đã nhận' in repeated.prompt
    assert db.query(Ticket).count()==1
    assert db.query(Notification).filter_by(kind='order_return').count()==1
    assert order.status=='delivered' and order.refunded_amount==0 and order.paid_amount==200000
    assert db.query(CustomerCollectionSession).filter_by(purpose='order_return').one().status=='completed'


def test_return_cannot_accept_other_shop_order(setup):
    db,conversation,*_=setup
    order=Order(business_id=2,customer_id=conversation.customer_id,order_number='CHAT-901',
        status='delivered',total_amount=10,paid_amount=10)
    db.add(order);db.commit()
    result=customer_return_reply(db,1,conversation.id,'Tôi muốn hoàn đơn CHAT-901')
    assert 'chưa tìm thấy' in result
    assert db.query(Ticket).count()==0


@pytest.mark.parametrize('text',['Chính sách hoàn tiền là gì?','Tôi không muốn hoàn đơn','CHAT-900'])
def test_no_return_session_for_policy_negation_or_unsolicited_code(setup,text):
    assert customer_return_reply(setup[0],1,setup[1].id,text) is None
