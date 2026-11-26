from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from test_business_request import setup
from app.models.sales import Order,OrderItem
from app.models.crm_job import CrmJob
from app.models.inventory import StockMovement
from app.services.order_service import transition_sales_order,refund_order_payment
from app.services.order_status_notification import send_order_status_notification
from app.api.sales import revenue_by_channel
import pytest
from app.services.order_service import SalesOrderOperationError


@pytest.mark.parametrize('target', ['processing', 'shipped'])
def test_fully_refunded_order_cannot_resume_fulfillment(setup, target):
    db, conversation, product, *_ = setup
    order = Order(business_id=1, customer_id=conversation.customer_id,
        order_number='REFUNDED-BLOCK', status='confirmed' if target == 'processing' else 'processing',
        total_amount=200000, paid_amount=200000, refunded_amount=200000,
        payment_status='refunded')
    db.add(order); db.flush()
    db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=1,
        unit_price=200000, line_total=200000)); db.commit()
    with pytest.raises(SalesOrderOperationError, match='hoàn đủ tiền'):
        transition_sales_order(db, order_id=order.id, to_status=target,
            business_id=1, actor_id=None)


def test_partial_then_full_refund_net_revenue_stock_and_notifications_are_idempotent(setup):
    db,conversation,product,*_=setup
    order=Order(business_id=1,customer_id=conversation.customer_id,conversation_id=conversation.id,
        order_number='REFUND-TEST',status='draft',total_amount=200000,paid_amount=200000)
    db.add(order);db.flush()
    db.add(OrderItem(order_id=order.id,product_id=product.id,quantity=1,unit_price=200000,line_total=200000));db.commit()
    initial_stock=product.stock_quantity
    for stage in ('confirmed','processing','shipped','delivered'):
        transition_sales_order(db,order_id=order.id,to_status=stage,business_id=1,actor_id=None)
    db.commit()
    assert product.stock_quantity==initial_stock-1
    tenant=SimpleNamespace(business_id=1)
    assert revenue_by_channel(db=db,tenant=tenant).total_revenue==200000
    args=dict(order_id=order.id,amount=Decimal(50000),reason='partial',idempotency_key='refund-a',actor_id=None,business_id=1)
    refund_order_payment(db,**args);db.commit()
    assert product.stock_quantity==initial_stock-1
    assert revenue_by_channel(db=db,tenant=tenant).total_revenue==150000
    assert refund_order_payment(db,**args)[2] is False
    refund_order_payment(db,**{**args,'amount':Decimal(150000),'idempotency_key':'refund-b'});db.commit()
    assert product.stock_quantity==initial_stock
    assert order.status=='refunded'
    assert revenue_by_channel(db=db,tenant=tenant).total_revenue==0
    assert db.query(StockMovement).filter_by(source_id=order.id,movement_type='sales_refund').count()==1
    jobs=[job for job in db.query(CrmJob).filter_by(kind='order.status_notification').all() if job.payload['status']=='refunded']
    assert len(jobs)==2
    with patch('app.services.auto_reply_service.send_text_reply',return_value={'message_id':'ok'}) as send:
        for job in jobs:send_order_status_notification(db,1,job.payload)
        assert '50.000' in send.call_args_list[0].kwargs['text']
        assert '150.000' in send.call_args_list[1].kwargs['text']
        assert 'Tổng tiền đã hoàn: 50.000' in send.call_args_list[0].kwargs['text']
        assert 'còn lại sau lần hoàn này: 150.000' in send.call_args_list[0].kwargs['text']
        assert 'Tổng tiền đã hoàn: 200.000' in send.call_args_list[1].kwargs['text']
        assert 'Đã hoàn đủ' in send.call_args_list[1].kwargs['text']
        assert send.call_args_list[0].kwargs['auto_reply_key']!=send.call_args_list[1].kwargs['auto_reply_key']
