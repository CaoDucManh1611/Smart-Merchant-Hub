from unittest.mock import patch

import pytest
from test_business_request import setup
from app.models.crm_job import CrmJob
from app.models.order_event import OrderEvent
from app.models.sales import Order, OrderItem
from app.services.order_service import transition_sales_order, SalesOrderOperationError
from app.services.order_status_notification import queue_order_status_notification, send_order_status_notification


def make_order(data):
    db, conversation, goods, *_ = data
    order = Order(business_id=1, customer_id=conversation.customer_id,
        conversation_id=conversation.id, order_number="STATUS-TEST", status="draft",
        total_amount=200000, paid_amount=200000)
    db.add(order); db.flush()
    db.add(OrderItem(order_id=order.id, product_id=goods.id, quantity=1, unit_price=200000, line_total=200000))
    db.commit()
    return order


def test_lifecycle_queues_each_committed_status_and_thanks_on_completion(setup):
    db=setup[0]; order=make_order(setup)
    stages=["confirmed","processing","shipped","delivered","completed"]
    for stage in stages:
        transition_sales_order(db,order_id=order.id,to_status=stage,actor_id=None,business_id=1)
        db.commit()
    jobs=db.query(CrmJob).filter_by(kind="order.status_notification").order_by(CrmJob.id).all()
    assert [job.payload["status"] for job in jobs]==stages
    with patch("app.services.auto_reply_service.send_text_reply", return_value={"message_id":"ok"}) as send:
        for job in jobs:
            send_order_status_notification(db,1,job.payload)
        assert send.call_count==5
        assert all(call.kwargs["conversation_id"]==setup[1].id for call in send.call_args_list)
        assert "chờ đóng gói" in send.call_args_list[0].kwargs["text"]
        assert "Cảm ơn" in send.call_args_list[-1].kwargs["text"]
        assert len({call.kwargs["auto_reply_key"] for call in send.call_args_list})==5
    event=db.query(OrderEvent).filter_by(order_id=order.id,to_status="completed").one()
    queue_order_status_notification(db,order,event)
    assert db.query(CrmJob).filter_by(kind="order.status_notification").count()==5
    with pytest.raises(SalesOrderOperationError):
        transition_sales_order(db,order_id=order.id,to_status="completed",actor_id=None,business_id=1)
    assert db.query(CrmJob).filter_by(kind="order.status_notification").count()==5


def test_rollback_never_leaves_customer_notification(setup):
    db=setup[0];order=make_order(setup)
    transition_sales_order(db,order_id=order.id,to_status="confirmed",actor_id=None,business_id=1)
    db.rollback()
    assert db.query(CrmJob).filter_by(kind="order.status_notification").count()==0
    assert db.get(Order,order.id).status=="draft"


def test_tenant_and_event_validation_prevent_wrong_recipient(setup):
    from app.services.job_service import JobBlocked
    db=setup[0];order=make_order(setup)
    transition_sales_order(db,order_id=order.id,to_status="confirmed",actor_id=None,business_id=1)
    db.commit()
    job=db.query(CrmJob).filter_by(kind="order.status_notification").one()
    with patch("app.services.auto_reply_service.send_text_reply") as send:
        send_order_status_notification(db,2,job.payload)
        with pytest.raises(JobBlocked):
            send_order_status_notification(db,1,{**job.payload,"status":"completed"})
        send.assert_not_called()


def test_service_completion_has_no_second_generic_thanks(setup):
    from datetime import datetime
    from app.models.industry_modules import Appointment
    from app.services.appointment_completion import complete_linked_service_order
    db,conversation,_,_,service,*_=setup
    appointment=Appointment(business_id=1,customer_id=conversation.customer_id,service_id=service.id,
        starts_at=datetime(2099,1,1),ends_at=datetime(2099,1,1,1),status="completed")
    db.add(appointment);db.flush()
    order=Order(business_id=1,customer_id=conversation.customer_id,conversation_id=conversation.id,
        order_number="SERVICE-THANKS",status="confirmed",total_amount=150000,paid_amount=150000,
        metadata_={"offering_type":"service","appointment_id":appointment.id})
    db.add(order);db.commit()
    complete_linked_service_order(db,appointment)
    assert db.query(CrmJob).filter_by(kind="order.status_notification").count()==0
    assert db.query(CrmJob).filter_by(kind="appointment.completion_thanks").count()==1
