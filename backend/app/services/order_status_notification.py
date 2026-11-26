"""Durable customer notifications for committed sales-order transitions."""
from app.models.conversation import Conversation
from app.models.order_event import OrderEvent
from app.models.sales import Order
from app.services.job_service import enqueue_job


STATUS_MESSAGES = {
    "cancelled": "Đơn {number} của bạn đã được hủy. Nếu cần đặt lại hoặc cần hỗ trợ, bạn cứ nhắn shop nhé.",
    "refunded": "",
    "confirmed": "Shop đã xác nhận đơn {number} của bạn. Đơn đang chờ đóng gói.",
    "processing": "Đơn {number} đang được shop đóng gói, chuẩn bị bàn giao vận chuyển.",
    "shipped": "Đơn {number} đã được bàn giao vận chuyển và đang giao đến bạn. Bạn chú ý điện thoại để nhận hàng nhé!",
    "delivered": "Đơn {number} đã được cập nhật là đã giao hàng. Nếu cần hỗ trợ, bạn hãy nhắn lại cho shop nhé.",
    "completed": "Đơn {number} đã hoàn tất. Cảm ơn bạn đã tin tưởng và mua hàng tại shop! Rất mong được phục vụ bạn lần sau.",
}


def queue_order_status_notification(db, order, event):
    if event.to_status == "confirmed":
        order.metadata_ = {**(order.metadata_ or {}),
            "confirmation_notification_status": "queued" if order.conversation_id else "no_conversation"}
    if not order.conversation_id or event.to_status not in STATUS_MESSAGES:
        return
    # Appointment completion owns its service-specific acknowledgement.
    if (order.metadata_ or {}).get("offering_type") == "service" and event.to_status not in {"confirmed", "cancelled"}:
        return
    db.flush()
    enqueue_job(db, business_id=order.business_id, kind="order.status_notification",
        payload={"order_id": order.id, "event_id": event.id, "status": event.to_status},
        idempotency_key=f"order:{order.id}:status-notification:{event.to_status}")


def send_order_status_notification(db, business_id, payload):
    from app.services.auto_reply_service import send_text_reply
    from app.services.job_service import JobBlocked
    status = payload.get("status")
    if status not in STATUS_MESSAGES:
        raise JobBlocked("Trạng thái thông báo đơn không hợp lệ.")
    order = db.query(Order).filter(Order.id == payload.get("order_id"), Order.business_id == business_id).first()
    if order is None:
        return
    event = db.query(OrderEvent).filter(OrderEvent.id == payload.get("event_id"),
        OrderEvent.business_id == business_id, OrderEvent.order_id == order.id,
        OrderEvent.order_type == "sales_order",
        OrderEvent.event_type == ("refund_created" if status == "refunded" else "status_changed"),
        *([] if status == "refunded" else [OrderEvent.to_status == status])).first()
    if event is None:
        raise JobBlocked("Không tìm thấy sự kiện đổi trạng thái của đơn.")
    conversation = db.query(Conversation).filter(Conversation.id == order.conversation_id,
        Conversation.business_id == business_id, Conversation.customer_id == order.customer_id).first()
    if conversation is None:
        return
    is_service = (order.metadata_ or {}).get("offering_type") == "service"
    if status == "refunded":
        from decimal import Decimal
        amount=Decimal((event.metadata_ or {}).get('amount','0'))
        formatted=f"{amount:,.0f}".replace(',','.')
        text=(f"Shop đã ghi nhận hoàn tiền {formatted} đồng cho đơn {order.order_number or order.id} của bạn. "
              "Bạn kiểm tra tài khoản hoặc phương thức nhận tiền đã thống nhất với nhân viên nhé. "
              "Nếu cần hỗ trợ thêm, bạn hãy nhắn lại cho shop. Cảm ơn bạn!")
        cumulative = (event.metadata_ or {}).get("cumulative_refunded")
        paid = (event.metadata_ or {}).get("paid_amount")
        if cumulative is not None and paid is not None:
            total_refunded = Decimal(str(cumulative))
            remaining = max(Decimal("0"), Decimal(str(paid)) - total_refunded)
            summary = (f"Tổng tiền đã hoàn: {total_refunded:,.0f} đồng. ".replace(",", "."))
            text += " " + summary + ("Đã hoàn đủ số tiền shop đã ghi nhận thu."
                if remaining == 0 else f"Số tiền đã thu còn lại sau lần hoàn này: {remaining:,.0f} đồng.".replace(",", "."))
    elif status == "cancelled":
        text = (f"Đơn dịch vụ {order.order_number or order.id} và lịch hẹn liên quan đã được hủy. Bạn cứ nhắn shop nếu cần đặt lại nhé."
            if is_service and (order.metadata_ or {}).get("appointment_id") else
            STATUS_MESSAGES[status].format(number=order.order_number or order.id))
        from decimal import Decimal
        if Decimal(order.paid_amount or 0) > Decimal(order.refunded_amount or 0):
            text += " Khoản đã thanh toán sẽ được shop kiểm tra và xử lý hoàn riêng; thông báo hủy đơn chưa phải xác nhận đã hoàn tiền."
    elif is_service:
        if status != "confirmed":
            return
        text = f"Shop đã xác nhận đơn dịch vụ {order.order_number or order.id} và lịch hẹn của bạn."
    else:
        text = STATUS_MESSAGES[status].format(number=order.order_number or order.id)
    # Keep the existing confirmation key to suppress a duplicate if a legacy
    # sender already delivered the same confirmation before a worker restart.
    key = (f"order-confirmed:{business_id}:{order.id}" if status == "confirmed"
           else f"order-refund:{business_id}:{order.id}:{event.id}" if status == "refunded"
           else f"order-status:{business_id}:{order.id}:{status}")
    result = send_text_reply(db=db, business_id=business_id, conversation_id=conversation.id,
        channel=conversation.channel, text=text, auto_reply_key=key,
        extra_metadata={"order_id": order.id, "order_event_id": event.id,
                        "notification_type": "order_status", "order_status": status})
    if result.get("idempotent"):
        from app.models.message import Message
        existing = db.query(Message).filter(Message.auto_reply_key == key,
            Message.conversation_id == conversation.id).first()
        if existing is not None and existing.status != "sent":
            raise JobBlocked("Kiểm tra kênh trước khi gửi lại thông báo chưa rõ kết quả.")
    if status == "confirmed":
        order.metadata_ = {**(order.metadata_ or {}), "confirmation_notification_status": "sent"}
        db.commit()
