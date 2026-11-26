"""Complete the linked service order and queue one customer acknowledgement."""
from app.models.sales import Order
from app.services.job_service import enqueue_job
from app.services.order_service import transition_sales_order


def complete_linked_service_order(db, appointment):
    if appointment.status != "completed":
        return None
    db.flush()
    order = db.query(Order).filter(
        Order.business_id == appointment.business_id,
        Order.customer_id == appointment.customer_id,
        Order.metadata_["appointment_id"].as_integer() == appointment.id,
    ).with_for_update().first()
    if order is None or (order.metadata_ or {}).get("offering_type") != "service":
        return None
    if order.status != "completed":
        transition_sales_order(db, order_id=order.id, to_status="completed",
            actor_id=None, business_id=appointment.business_id)
    if order.conversation_id:
        enqueue_job(db, business_id=appointment.business_id, kind="appointment.completion_thanks",
            payload={"appointment_id": appointment.id, "order_id": order.id},
            idempotency_key=f"appointment:{appointment.id}:completion-thanks")
    return order


def send_completion_thanks(db, business_id, payload):
    from app.models.industry_modules import Appointment, AppointmentService
    from app.models.conversation import Conversation
    from app.services.auto_reply_service import send_text_reply
    appointment = db.query(Appointment).filter(Appointment.id == payload.get("appointment_id"),
        Appointment.business_id == business_id, Appointment.status == "completed").first()
    order = db.query(Order).filter(Order.id == payload.get("order_id"),
        Order.business_id == business_id, Order.status == "completed").first()
    if appointment is None or order is None or (order.metadata_ or {}).get("appointment_id") != appointment.id:
        return
    conversation = db.query(Conversation).filter(Conversation.id == order.conversation_id,
        Conversation.business_id == business_id, Conversation.customer_id == appointment.customer_id).first()
    if conversation is None:
        return
    service = db.query(AppointmentService).filter(AppointmentService.id == appointment.service_id,
        AppointmentService.business_id == business_id).first()
    text = (f"Dịch vụ {service.name if service else 'của bạn'} (đơn {order.order_number}) đã hoàn tất. "
            "Cảm ơn bạn đã tin tưởng và sử dụng dịch vụ của shop! Rất mong được phục vụ bạn lần sau.")
    send_text_reply(db=db, business_id=business_id, conversation_id=conversation.id,
        channel=conversation.channel, text=text,
        auto_reply_key=f"appointment:{appointment.id}:completion-thanks")
