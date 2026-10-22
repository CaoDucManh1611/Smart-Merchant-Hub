"""Notify only the conversation explicitly linked to a confirmed sales order."""

from app.models.conversation import Conversation
from app.services.auto_reply_service import send_text_reply


def notify_order_confirmation(db, *, order, business_id):
    conversation = db.query(Conversation).filter(
        Conversation.id == order.conversation_id,
        Conversation.business_id == business_id,
        Conversation.customer_id == order.customer_id,
    ).first() if order.conversation_id is not None else None
    status = "no_conversation"
    if conversation is not None:
        lines = [f"Shop đã xác nhận đơn {order.order_number or order.id} của bạn."]
        lines.extend(f"- {item.product.name if item.product else 'Sản phẩm'}: {item.quantity} × {item.unit_price:,.0f} đ" for item in order.items)
        lines.append(f"Tổng đơn: {order.total_amount:,.0f} đ. Cảm ơn bạn!")
        try:
            send_text_reply(
                db=db, conversation_id=conversation.id, channel=conversation.channel,
                text="\n".join(lines), business_id=business_id,
                auto_reply_key=f"order-confirmed:{business_id}:{order.id}",
                extra_metadata={"order_id": order.id, "notification_type": "order_confirmation"},
            )
            status = "sent"
        except Exception:
            # A provider failure must not undo a committed inventory transition.
            db.rollback()
            status = "failed"
    order.metadata_ = {**(order.metadata_ or {}), "confirmation_notification_status": status}
    db.commit()
