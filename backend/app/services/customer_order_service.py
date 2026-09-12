"""Safe customer-facing order lookup and support actions.

Customer actions always resolve through the current conversation.  A customer
can therefore only see or act on orders belonging to the tenant-scoped
customer attached to that conversation; an order number alone is never a
credential.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
import unicodedata

from sqlalchemy.orm import Session

from app.models.business import User
from app.models.conversation import Conversation
from app.models.crm_extended import ConversationAssignment
from app.models.order_event import OrderEvent
from app.models.sales import Order
from app.models.ticket import Ticket, TicketEvent
from app.services.audit_service import record_audit
from app.services.order_service import SalesOrderOperationError, transition_sales_order


ORDER_STATUS_LABELS = {
    "draft": "Đơn nháp",
    "confirmed": "Đã xác nhận",
    "processing": "Đang xử lý",
    "shipped": "Đang giao",
    "delivered": "Đã giao",
    "completed": "Hoàn thành",
    "cancelled": "Đã hủy",
    "refunded": "Đã hoàn tiền",
}

ORDER_NUMBER_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b", re.IGNORECASE)
STATUS_TERMS = ("trạng thái đơn", "kiểm tra đơn", "tra cứu đơn", "đơn hàng của tôi", "đơn của tôi", "theo dõi đơn")
DRAFT_STATUS_TERMS = ("đơn nháp", "đơn hàng nháp", "đơn draft", "draft order")
CANCEL_TERMS = ("hủy đơn", "huỷ đơn", "hủy hàng", "huỷ hàng", "cancel đơn")
REFUND_TERMS = ("hoàn tiền", "hoàn hàng", "đổi trả", "trả hàng", "hàng lỗi", "hàng bị lỗi")


def _format_vnd(value: object) -> str:
    try:
        amount = Decimal(str(value or 0))
    except Exception:
        amount = Decimal("0")
    return f"{amount:,.0f}".replace(",", ".")


def _fold_order_text(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    normalized = normalized.replace("đ", "d")
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _friendly_action_reason(reason: str | None, *, action: str) -> str:
    messages = {
        "order_not_found": "Mình chưa tìm thấy đơn phù hợp với thông tin bạn gửi.",
        "order_cancelled": "đơn này đã được hủy trước đó",
        "order_refunded": "đơn này đã được hoàn tiền trước đó",
        "order_already_closed": "đơn này đã được đóng trước đó",
        "staff_review_required": "đơn này cần nhân viên kiểm tra trước khi hủy",
    }
    if reason in messages:
        return messages[reason]
    return "chưa thể xử lý tự động; mình sẽ chuyển nhân viên kiểm tra" if action == "cancel" else "chưa thể tiếp nhận tự động"


class CustomerOrderActionError(ValueError):
    """A safe, machine-readable customer order action error."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def detect_customer_order_intent(text: str | None) -> str | None:
    """Detect only deterministic, high-confidence customer order intents."""
    normalized = str(text or "").casefold()
    if any(term in normalized for term in REFUND_TERMS):
        return "refund"
    if any(term in normalized for term in CANCEL_TERMS):
        return "cancel"
    if any(term in normalized for term in DRAFT_STATUS_TERMS):
        return "draft_status"
    # Include the natural Vietnamese phrasing used in chat (“tôi có đơn hàng
    # nào không?”).  These are read-only order lookups and must never fall
    # through to the knowledge-base fallback.
    if any(term in normalized for term in ("tôi có đơn hàng nào", "có đơn hàng nào", "đơn hàng nào")):
        return "status"
    if any(term in normalized for term in STATUS_TERMS):
        return "status"
    return None


def extract_order_number(text: str | None) -> str | None:
    match = ORDER_NUMBER_PATTERN.search(str(text or ""))
    return match.group(0).upper() if match else None


def _customer_order_reference(
    db: Session,
    business_id: int,
    conversation_id: int,
    order_number: str | None,
) -> tuple[dict, str | None]:
    listed = list_customer_orders(
        db,
        business_id,
        conversation_id,
        order_number=order_number,
    )
    if not listed["found"]:
        return listed, None
    if listed["requires_order_identifier"]:
        return listed, None
    return listed, listed["items"][0]["order_number"]


def customer_order_reply(
    db: Session,
    business_id: int,
    conversation_id: int,
    text: str,
) -> str | None:
    """Handle safe order intents before RAG and return a customer reply.

    The function is deliberately deterministic: it never exposes an order
    outside the conversation customer and never performs an irreversible
    refund.  Returning ``None`` lets the normal RAG path handle the message.
    """
    intent = detect_customer_order_intent(text)
    if intent is None:
        return None
    order_number = extract_order_number(text)

    if intent == "draft_status":
        listed = list_customer_orders(
            db,
            business_id,
            conversation_id,
            order_number=order_number,
            status="draft",
        )
        if not listed.get("found"):
            return "Mình chưa thấy đơn nháp nào của bạn. Khi cần mua sản phẩm, bạn cứ nhắn mình nhé."
        if order_number:
            payload = listed["items"][0]
            return (
                f"Đơn nháp {payload['order_number']} đang chờ xác nhận. "
                f"Tổng tiền: {_format_vnd(payload['total_amount'])} đồng."
            )
        summaries = "; ".join(
            f"{item['order_number']} ({_format_vnd(item['total_amount'])} đồng)"
            for item in listed["items"][:5]
        )
        return f"Bạn đang có {len(listed['items'])} đơn nháp: {summaries}. Bạn muốn xác nhận đơn nào?"

    if intent == "status":
        if order_number:
            result = get_customer_order_status(db, business_id, conversation_id, {"order_number": order_number})
        else:
            result, order_number = _customer_order_reference(db, business_id, conversation_id, None)
        if not result.get("found"):
            return "Mình chưa tìm thấy đơn hàng thuộc tài khoản của bạn. Bạn gửi giúp mình mã đơn nhé."
        if result.get("requires_order_identifier"):
            refs = ", ".join(item["order_number"] for item in result["items"][:5])
            return f"Mình thấy nhiều đơn của bạn ({refs}). Bạn cho mình mã đơn cần kiểm tra nhé."
        payload = result if order_number and result.get("found") and "status_label" in result else result["items"][0]
        tracking = f" Mã vận đơn: {payload['tracking_code']}." if payload.get("tracking_code") else ""
        return (
            f"Đơn {payload['order_number']} đang ở trạng thái **{payload['status_label']}**. "
            f"Tổng tiền: {_format_vnd(payload['total_amount'])} đồng."
            f"{tracking}"
        )

    listed = list_customer_orders(
        db,
        business_id,
        conversation_id,
        order_number=order_number,
    )
    if not listed.get("found"):
        return "Mình chưa tìm thấy đơn hàng thuộc tài khoản của bạn. Bạn gửi giúp mình mã đơn nhé."

    if order_number:
        resolved_number = order_number
    elif intent in {"cancel", "refund"}:
        candidates = _action_order_candidates(listed["items"], text)
        if len(candidates) != 1:
            return _format_action_choices(candidates or listed["items"], action=intent)
        resolved_number = candidates[0]["order_number"]
    else:
        if listed.get("requires_order_identifier"):
            refs = ", ".join(item["order_number"] for item in listed["items"][:5])
            return f"Mình thấy nhiều đơn của bạn ({refs}). Bạn cho mình mã đơn cần xử lý nhé."
        resolved_number = listed["items"][0]["order_number"]

    arguments = {"order_number": resolved_number, "reason": text[:500]}
    if intent == "cancel":
        result = request_order_cancellation(db, business_id, conversation_id, arguments)
        if not result.get("accepted"):
            reason = result.get("reason")
            if reason in {"order_cancelled", "order_refunded"}:
                return f"Mình chưa thể hủy đơn {resolved_number}: {_friendly_action_reason(reason, action='cancel')}."
            if reason == "order_not_found":
                return f"Mình chưa thể hủy đơn {resolved_number}: {_friendly_action_reason(reason, action='cancel')}"
            return f"Mình chưa thể hủy đơn {resolved_number}; {_friendly_action_reason(reason, action='cancel')}."
        if result.get("mode") == "self_service":
            return f"Mình đã hủy đơn {resolved_number} theo yêu cầu của bạn."
        return f"Mình đã chuyển yêu cầu hủy đơn {resolved_number} cho nhân viên kiểm tra. Mã ticket: {result['ticket_id']}."

    result = request_order_refund(db, business_id, conversation_id, arguments)
    if not result.get("accepted"):
        reason = result.get("reason")
        return f"Mình chưa thể tiếp nhận yêu cầu hoàn đơn {resolved_number}: {_friendly_action_reason(reason, action='refund')}."
    return f"Mình đã tạo yêu cầu hoàn/đổi trả cho đơn {resolved_number}. Nhân viên sẽ kiểm tra và liên hệ lại, mã ticket: {result['ticket_id']}."


def _conversation(db: Session, business_id: int, conversation_id: int) -> Conversation:
    row = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.business_id == business_id,
    ).first()
    if row is None:
        raise CustomerOrderActionError("conversation_not_found")
    return row


def _orders_for_conversation(
    db: Session,
    business_id: int,
    conversation_id: int,
    *,
    order_number: str | None = None,
    order_id: int | None = None,
    status: str | None = None,
) -> tuple[Conversation, list[Order]]:
    conversation = _conversation(db, business_id, conversation_id)
    query = db.query(Order).filter(
        Order.business_id == business_id,
        Order.customer_id == conversation.customer_id,
    )
    if order_number:
        query = query.filter(Order.order_number == order_number.strip())
    if order_id is not None:
        query = query.filter(Order.id == int(order_id))
    if status:
        query = query.filter(Order.status == status.strip().lower())
    orders = query.order_by(Order.created_at.desc(), Order.id.desc()).limit(20).all()
    return conversation, orders


def _order_payload(order: Order) -> dict:
    return {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "status_label": ORDER_STATUS_LABELS.get(order.status, order.status),
        "total_amount": float(order.total_amount or 0),
        "payment_status": order.payment_status,
        "paid_amount": float(order.paid_amount or 0),
        "refunded_amount": float(order.refunded_amount or 0),
        "shipping_status": order.shipping_status,
        "tracking_code": order.tracking_code,
        "channel": getattr(order.conversation, "channel", None),
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "items": [
            {
                "name": item.product_name_snapshot or (item.product.name if item.product else None),
                "sku": item.sku_snapshot or (item.product.sku if item.product else None),
                "quantity": item.quantity,
                "unit_price": float(item.unit_price or 0),
                "line_total": float(item.line_total or 0),
            }
            for item in (order.items or [])
        ],
    }


def _format_action_choices(items: list[dict], *, action: str) -> str:
    """Show enough context for a customer to select the right order."""
    if not items:
        return "Mình chưa tìm thấy đơn phù hợp với mã món hoặc kênh bạn vừa gửi. Bạn kiểm tra lại giúp mình nhé."
    verb = "hủy" if action == "cancel" else "hoàn/đổi trả"
    lines = []
    for item in items[:5]:
        products = ", ".join(
            f"{row.get('name') or row.get('sku') or 'sản phẩm'} ×{row.get('quantity', 1)}"
            for row in item.get("items", [])
        ) or "chưa có sản phẩm"
        channel = item.get("channel") or "không rõ kênh"
        lines.append(
            f"- {item['order_number']} · {channel} · {products} · "
            f"{_format_vnd(item['total_amount'])} đồng · {item['status_label']}"
        )
    return (
        f"Mình tìm thấy các đơn có thể {verb}:\n" + "\n".join(lines) +
        f"\nBạn gửi mã đơn, tên món hoặc kênh cần {verb} nhé."
    )


def _action_order_candidates(items: list[dict], text: str) -> list[dict]:
    """Filter customer-owned orders by product/SKU or channel mentions."""
    folded = _fold_order_text(text)
    channel_terms = {
        channel for channel in ("telegram", "zalo", "facebook", "instagram", "messenger", "whatsapp")
        if re.search(rf"\b{re.escape(channel)}\b", folded)
    }
    product_matches = []
    for item in items:
        values = []
        for product in item.get("items", []):
            values.extend((product.get("name"), product.get("sku")))
        if any(value and _fold_order_text(value) in folded for value in values):
            product_matches.append(item)
    candidates = product_matches or list(items)
    if channel_terms:
        candidates = [item for item in candidates if _fold_order_text(item.get("channel")) in channel_terms]
    return candidates


def list_customer_orders(
    db: Session,
    business_id: int,
    conversation_id: int,
    *,
    order_number: str | None = None,
    order_id: int | None = None,
    status: str | None = None,
) -> dict:
    """Return only orders owned by the conversation's canonical customer."""
    conversation, orders = _orders_for_conversation(
        db,
        business_id,
        conversation_id,
        order_number=order_number,
        order_id=order_id,
        status=status,
    )
    return {
        "found": bool(orders),
        "customer_id": conversation.customer_id,
        "requires_order_identifier": not order_number and order_id is None and len(orders) > 1,
        "items": [_order_payload(order) for order in orders],
    }


def _resolve_order(
    db: Session,
    business_id: int,
    conversation_id: int,
    arguments: dict,
) -> tuple[Conversation, Order] | tuple[None, None]:
    order_number = str(arguments.get("order_number") or "").strip() or None
    raw_order_id = arguments.get("order_id")
    try:
        order_id = int(raw_order_id) if raw_order_id is not None else None
    except (TypeError, ValueError):
        return None, None
    conversation, orders = _orders_for_conversation(
        db,
        business_id,
        conversation_id,
        order_number=order_number,
        order_id=order_id,
    )
    if not orders:
        return None, None
    if not order_number and order_id is None and len(orders) > 1:
        raise CustomerOrderActionError("order_identifier_required")
    return conversation, orders[0]


def get_customer_order_status(db: Session, business_id: int, conversation_id: int, arguments: dict) -> dict:
    conversation, order = _resolve_order(db, business_id, conversation_id, arguments)
    if order is None:
        return {"found": False, "reason": "order_not_found"}
    payload = _order_payload(order)
    payload["customer_id"] = conversation.customer_id
    payload["found"] = True
    return payload


def _assignee(db: Session, business_id: int) -> User | None:
    return db.query(User).filter(
        User.business_id == business_id,
        User.is_active.is_(True),
        User.role.in_(("agent", "business_agent", "admin", "business_admin", "owner")),
    ).order_by(User.id.asc()).first()


def _staff_ticket(
    db: Session,
    *,
    business_id: int,
    conversation: Conversation,
    order: Order,
    action: str,
    reason: str,
) -> Ticket:
    marker = f"order_id={order.id}"
    existing = db.query(Ticket).filter(
        Ticket.business_id == business_id,
        Ticket.conversation_id == conversation.id,
        Ticket.status.in_(("open", "pending")),
    ).order_by(Ticket.id.desc()).all()
    for ticket in existing:
        if marker in (ticket.description or ""):
            conversation.bot_mode = "human"
            return ticket

    assignee = _assignee(db, business_id)
    ticket = Ticket(
        business_id=business_id,
        customer_id=conversation.customer_id,
        conversation_id=conversation.id,
        title=f"Yêu cầu {action} đơn {order.order_number}",
        description=(
            f"{marker}\nMã đơn: {order.order_number}\n"
            f"Khách yêu cầu: {reason[:500]}"
        ),
        status="open",
        priority="high",
        assigned_user_id=assignee.id if assignee else None,
        sla_due_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8),
    )
    conversation.bot_mode = "human"
    if assignee:
        conversation.assigned_user_id = assignee.id
        db.add(ConversationAssignment(
            conversation_id=conversation.id,
            user_id=assignee.id,
            assignment_type="customer_order_action",
        ))
    db.add(ticket)
    db.flush()
    db.add(TicketEvent(
        business_id=business_id,
        ticket_id=ticket.id,
        event_type="created",
        to_value="high",
    ))
    db.add(OrderEvent(
        business_id=business_id,
        order_type="sales_order",
        order_id=order.id,
        event_type="customer_support_requested",
        metadata_={"action": action, "ticket_id": ticket.id, "reason": reason[:500]},
    ))
    record_audit(
        db,
        business_id=business_id,
        actor_type="bot",
        action=f"customer_order_{action}",
        resource_type="sales_order",
        resource_id=order.id,
        metadata={"conversation_id": conversation.id, "ticket_id": ticket.id},
    )
    return ticket


def request_order_cancellation(db: Session, business_id: int, conversation_id: int, arguments: dict) -> dict:
    conversation, order = _resolve_order(db, business_id, conversation_id, arguments)
    if order is None:
        return {"accepted": False, "reason": "order_not_found"}
    reason = str(arguments.get("reason") or "Khách yêu cầu hủy đơn").strip()
    if order.status == "cancelled":
        return {"accepted": False, "reason": "order_cancelled", "order": _order_payload(order)}
    if order.status == "refunded":
        return {"accepted": False, "reason": "order_refunded", "order": _order_payload(order)}

    net_paid = Decimal(order.paid_amount or 0) - Decimal(order.refunded_amount or 0)
    if order.status in {"draft", "confirmed"} and net_paid <= 0:
        try:
            transition_sales_order(
                db,
                order_id=order.id,
                to_status="cancelled",
                actor_id=None,
                business_id=business_id,
            )
        except SalesOrderOperationError as exc:
            raise CustomerOrderActionError(f"cancel_failed:{exc.detail}") from exc
        order.cancel_reason = reason[:2000]
        record_audit(
            db,
            business_id=business_id,
            actor_type="bot",
            action="customer_order_cancelled",
            resource_type="sales_order",
            resource_id=order.id,
            metadata={"conversation_id": conversation.id, "reason": reason[:500]},
        )
        return {"accepted": True, "mode": "self_service", "order": _order_payload(order)}

    ticket = _staff_ticket(
        db,
        business_id=business_id,
        conversation=conversation,
        order=order,
        action="hủy/hoàn",
        reason=reason,
    )
    return {
        "accepted": True,
        "mode": "staff_review",
        "reason": "staff_review_required",
        "ticket_id": ticket.id,
        "order": _order_payload(order),
    }


def request_order_refund(db: Session, business_id: int, conversation_id: int, arguments: dict) -> dict:
    conversation, order = _resolve_order(db, business_id, conversation_id, arguments)
    if order is None:
        return {"accepted": False, "reason": "order_not_found"}
    if order.status == "refunded":
        return {"accepted": False, "reason": "order_already_refunded", "order": _order_payload(order)}
    reason = str(arguments.get("reason") or "Khách yêu cầu hoàn/đổi trả").strip()
    ticket = _staff_ticket(
        db,
        business_id=business_id,
        conversation=conversation,
        order=order,
        action="hoàn/đổi trả",
        reason=reason,
    )
    return {
        "accepted": True,
        "mode": "staff_review",
        "reason": "refund_requires_staff_review",
        "ticket_id": ticket.id,
        "order": _order_payload(order),
    }
