from unittest.mock import patch
import pytest
from test_business_request import setup
from test_order_status_notification import make_order
from app.models.crm_job import CrmJob
from app.models.order_event import OrderEvent
from app.services.order_service import transition_sales_order
from app.services.order_status_notification import queue_order_status_notification,send_order_status_notification

@pytest.mark.parametrize('channel',['zalo','telegram','facebook'])
@pytest.mark.parametrize('kind',['goods','service'])
def test_cancel_notifies_same_customer_channel_once(setup,channel,kind):
 db,c,*_=setup;c.channel=channel;order=make_order(setup)
 order.metadata_={'offering_type':kind};db.commit()
 transition_sales_order(db,order_id=order.id,to_status='cancelled',actor_id=None,business_id=1);db.commit()
 event=db.query(OrderEvent).filter_by(order_id=order.id,to_status='cancelled').one()
 queue_order_status_notification(db,order,event);db.commit()
 jobs=db.query(CrmJob).filter_by(kind='order.status_notification').all()
 assert len(jobs)==1 and jobs[0].payload['status']=='cancelled'
 with patch('app.services.auto_reply_service.send_text_reply',return_value={'message_id':'ok'}) as send:
  send_order_status_notification(db,1,jobs[0].payload)
 assert send.call_args.kwargs['channel']==channel and send.call_args.kwargs['conversation_id']==c.id
 text=send.call_args.kwargs['text']
 assert 'đã được hủy' in text and order.order_number in text
 assert 'chưa phải xác nhận đã hoàn tiền' in text
 assert order.paid_amount==200000 and order.refunded_amount==0


def test_cancel_rollback_does_not_notify(setup):
 db,*_=setup;order=make_order(setup)
 transition_sales_order(db,order_id=order.id,to_status='cancelled',actor_id=None,business_id=1)
 db.rollback()
 assert not db.query(CrmJob).filter_by(kind='order.status_notification').all()
