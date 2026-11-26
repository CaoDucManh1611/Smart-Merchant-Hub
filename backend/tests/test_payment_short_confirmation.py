from test_business_request import setup
from app.models.sales import Order
from app.models.message import Message
from app.models.notification import Notification
from app.services.customer_order_service import payment_report_confirmation_reply
from app.services.order_payment_request import payment_state
from unittest.mock import patch


def prepare(data):
 db,c,*_=data
 order=Order(business_id=1,customer_id=c.customer_id,conversation_id=c.id,order_number='CHAT-13',status='draft',total_amount=118000,paid_amount=0,metadata_={'payment_flow':'prepay_then_confirm','payment_method':'bank_transfer','payment_request':{'amount':'118000','lines':[{'label':'Tiền hàng','amount':'118000'}]}})
 db.add(order)
 db.add(Message(conversation_id=c.id,channel=c.channel,direction='outbound',sender_type='bot',status='sent',content='Đơn CHAT-13\nMã QR: https://img.vietqr.io/image/example.png'))
 db.commit();return db,c,order


def test_short_confirmation_reports_payment_but_never_marks_paid(setup):
 db,c,o=prepare(setup)
 for _ in range(2):
  reply=payment_report_confirmation_reply(db,1,c.id,'Xác nhận')
  assert 'đối soát' in reply and 'CHAT-13' in reply
 assert payment_state(o)=='awaiting_reconciliation'
 assert o.paid_amount==0 and o.status=='pending_confirmation'
 assert db.query(Notification).filter_by(kind='payment_review').count()==1
 from app.models.order_event import OrderEvent
 assert db.query(OrderEvent).filter_by(order_id=o.id,to_status='pending_confirmation').count()==1
 assert 'chờ nhân viên xác nhận' in reply


def test_graph_handles_confirmation_without_ai(setup):
 from app.core.config import settings
 from app.services.conversation_graph import graph_reply
 db,c,o=prepare(setup)
 with patch.object(settings,'CATALOG_DIALOGUE_ENABLED',True),patch('app.services.catalog_dialogue._interpret',side_effect=AssertionError('payment confirmation must not need AI')):
  r=graph_reply(db,business_id=1,conversation=c,query='Xác nhận',job_key='payment-short-confirm')
 assert r.status=='payment_reported' and payment_state(o)=='awaiting_reconciliation'


def test_confirmation_without_payment_prompt_is_not_payment(setup):
 db,c,o=prepare(setup)
 db.add(Message(conversation_id=c.id,channel=c.channel,direction='outbound',sender_type='bot',status='sent',content='Bạn xác nhận chọn sản phẩm này?'));db.commit()
 assert payment_report_confirmation_reply(db,1,c.id,'Xác nhận') is None
 assert 'customer_payment_reported_at' not in o.metadata_


def test_reporting_payment_keeps_inventory_and_paid_amount_unchanged(setup):
 from app.models.sales import OrderItem
 db,c,o=prepare(setup)
 product=setup[2];product.stock_quantity=20;product.reserved_quantity=2
 o.reserved_quantity=2
 db.add(OrderItem(order_id=o.id,product_id=product.id,quantity=2,unit_price=59000,line_total=118000))
 db.commit()
 payment_report_confirmation_reply(db,1,c.id,'Xác nhận')
 assert o.status=='pending_confirmation' and o.paid_amount==0
 assert product.stock_quantity==20 and product.reserved_quantity==2 and o.reserved_quantity==2
