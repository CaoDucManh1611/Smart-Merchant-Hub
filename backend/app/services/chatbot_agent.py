"""Small, auditable agent layer used by the sales chatbot.

The LLM never receives arbitrary Python access.  It can only request names in
``AGENT_TOOLS`` and every implementation checks the business and conversation
tenant before touching CRM data.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.business import User
from app.models.chatbot import ChatbotConfig
from app.models.canned_response import CannedResponse
from app.models.conversation import Conversation
from app.models.customer_fact import CustomerFact
from app.models.crm_extended import ConversationAssignment, CustomerTag, Tag
from app.models.message import Message
from app.models.sales import Order, OrderItem, Product
from app.models.ticket import Ticket, TicketEvent
from app.services.audit_service import record_audit


AGENT_TOOLS = {
    "xem_ton_kho": "Kiểm tra tồn kho theo SKU hoặc tên sản phẩm.",
    "tim_san_pham": "Tìm sản phẩm đang bán trong catalog của shop.",
    "tao_don_nhap": "Tạo đề xuất đơn nháp sau khi khách đã xác nhận sản phẩm và số lượng.",
    "tao_ticket": "Tạo ticket hỗ trợ và đặt mức ưu tiên.",
    "gan_tag": "Gắn tag cho hồ sơ khách hàng.",
    "chuyen_nhan_vien": "Bật takeover và chuyển hội thoại cho nhân viên.",
    "dat_lich_cham_soc": "Tạo yêu cầu chăm sóc lại để scheduler xử lý.",
    "dung_mau_tra_loi": "Lấy nội dung mẫu trả lời đã được shop duyệt.",
}


ESCALATION_TERMS = (
    "gặp nhân viên", "nhân viên", "khiếu nại", "hoàn tiền", "đổi trả",
    "hàng lỗi", "hàng bị lỗi", "bị hỏng", "không nhận được", "hỗ trợ gấp",
)


def _conversation(db: Session, business_id: int, conversation_id: int) -> Conversation:
    row = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.business_id == business_id,
    ).first()
    if row is None:
        raise ValueError("conversation_not_found")
    return row


def build_agent_memory(db: Session, business_id: int, conversation_id: int) -> dict:
    conversation = _conversation(db, business_id, conversation_id)
    messages = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.received_at.asc(), Message.id.asc()).limit(30).all()
    history = []
    for message in messages:
        role = "user" if message.direction == "inbound" or message.sender_type == "customer" else "assistant"
        if message.content:
            history.append({"role": role, "content": message.content, "sender_type": message.sender_type})

    facts = db.query(CustomerFact).filter(
        CustomerFact.business_id == business_id,
        CustomerFact.customer_id == conversation.customer_id,
    ).order_by(CustomerFact.observed_at.desc(), CustomerFact.id.desc()).limit(20).all()
    tags = db.query(Tag).join(CustomerTag, CustomerTag.tag_id == Tag.id).filter(
        CustomerTag.business_id == business_id,
        CustomerTag.customer_id == conversation.customer_id,
    ).order_by(Tag.name.asc()).all()
    products = db.query(Product).filter(
        Product.business_id == business_id,
        Product.status == "active",
    ).order_by(Product.updated_at.desc(), Product.id.desc()).limit(10).all()
    orders = db.query(Order).filter(
        Order.business_id == business_id,
        Order.customer_id == conversation.customer_id,
    ).order_by(Order.created_at.desc(), Order.id.desc()).limit(5).all()
    return {
        "conversation_id": conversation.id,
        "customer_id": conversation.customer_id,
        "bot_mode": conversation.bot_mode,
        "history": history,
        "facts": [{"key": fact.fact_key, "type": fact.fact_type, "value": fact.fact_value_json, "confidence": fact.confidence} for fact in facts],
        "tags": [tag.name for tag in tags],
        "recent_orders": [
            {
                "id": order.id,
                "order_number": order.order_number,
                "status": order.status,
                "total_amount": float(order.total_amount or 0),
                "created_at": order.created_at.isoformat() if order.created_at else None,
                "items": [
                    {
                        "name": item.product_name_snapshot or (item.product.name if item.product else None),
                        "quantity": item.quantity,
                        "line_total": float(item.line_total or 0),
                    }
                    for item in (order.items or [])
                ],
            }
            for order in orders
        ],
        "recent_products": [{"id": p.id, "sku": p.sku, "name": p.name, "price": float(p.price or 0)} for p in products],
    }


def is_business_open(db: Session, business_id: int, now: datetime | None = None) -> bool:
    config = db.query(ChatbotConfig).filter(ChatbotConfig.business_id == business_id).first()
    if not isinstance(config, ChatbotConfig):
        return True
    hours = (config.business_hours or {}) if config else {}
    if not hours:
        return True
    timezone_name = hours.get("timezone", "Asia/Ho_Chi_Minh")
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = timezone.utc
    current = (now or datetime.now(timezone.utc))
    if current.tzinfo is None:
        current = current.replace(tzinfo=tz)
    current = current.astimezone(tz)
    day = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[current.weekday()]
    windows = hours.get(day, [])
    if not windows:
        return False
    current_minutes = current.hour * 60 + current.minute
    for start, end in windows:
        try:
            start_minutes = int(start[:2]) * 60 + int(start[3:])
            end_minutes = int(end[:2]) * 60 + int(end[3:])
        except (TypeError, ValueError):
            continue
        if start_minutes <= current_minutes <= end_minutes:
            return True
    return False


def _available(product: Product) -> int:
    return max(int(product.stock_quantity or 0) - int(product.reserved_quantity or 0), 0)


def _find_assignee(db: Session, business_id: int) -> User | None:
    return db.query(User).filter(
        User.business_id == business_id,
        User.is_active.is_(True),
        User.role.in_(("agent", "business_agent", "admin", "business_admin", "owner")),
    ).order_by(User.id.asc()).first()


def route_escalation(db: Session, business_id: int, conversation_id: int, text: str) -> Ticket | None:
    if not any(term in (text or "").casefold() for term in ESCALATION_TERMS):
        return None
    conversation = _conversation(db, business_id, conversation_id)
    existing = db.query(Ticket).filter(
        Ticket.business_id == business_id,
        Ticket.conversation_id == conversation_id,
        Ticket.status.in_(("open", "pending")),
    ).order_by(Ticket.id.desc()).first()
    if existing:
        conversation.bot_mode = "human"
        return existing
    assignee = _find_assignee(db, business_id)
    ticket = Ticket(
        business_id=business_id,
        customer_id=conversation.customer_id,
        conversation_id=conversation_id,
        title="Khách cần nhân viên hỗ trợ",
        description=text[:10000],
        status="open",
        priority="high",
        assigned_user_id=assignee.id if assignee else None,
        sla_due_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8),
    )
    conversation.bot_mode = "human"
    if assignee:
        conversation.assigned_user_id = assignee.id
        db.add(ConversationAssignment(conversation_id=conversation.id, user_id=assignee.id, assignment_type="bot_escalation"))
    db.add(ticket)
    db.flush()
    db.add(TicketEvent(business_id=business_id, ticket_id=ticket.id, event_type="created", to_value="high"))
    record_audit(db, business_id=business_id, action="chatbot_escalated", resource_type="ticket", resource_id=ticket.id, metadata={"conversation_id": conversation_id, "reason": text[:500]})
    return ticket


def _search_products(db: Session, business_id: int, query: str | None = None):
    q = db.query(Product).filter(Product.business_id == business_id, Product.status == "active")
    if query:
        term = f"%{query.strip()}%"
        q = q.filter(or_(Product.name.ilike(term), Product.sku.ilike(term), Product.description.ilike(term)))
    return q.order_by(Product.name.asc(), Product.id.asc()).limit(20).all()


def execute_chatbot_tool(db: Session, business_id: int, conversation_id: int, tool_name: str, arguments: dict | None = None) -> dict:
    if tool_name not in AGENT_TOOLS:
        raise ValueError("tool_not_allowed")
    _conversation(db, business_id, conversation_id)
    args = arguments or {}
    if tool_name == "tim_san_pham":
        products = _search_products(db, business_id, args.get("query"))
        return {"items": [{"id": p.id, "sku": p.sku, "name": p.name, "price": float(p.price or 0), "available": _available(p)} for p in products]}
    if tool_name == "xem_ton_kho":
        q = db.query(Product).filter(Product.business_id == business_id)
        if args.get("sku"):
            q = q.filter(Product.sku == str(args["sku"]))
        elif args.get("product_id"):
            q = q.filter(Product.id == int(args["product_id"]))
        else:
            q = q.filter(Product.name.ilike(f"%{args.get('query', '')}%"))
        product = q.first()
        if product is None:
            return {"found": False, "available": 0}
        return {"found": True, "product_id": product.id, "sku": product.sku, "name": product.name, "available": _available(product)}
    if tool_name == "gan_tag":
        conversation = _conversation(db, business_id, conversation_id)
        tag_name = str(args.get("tag") or "").strip()
        if not tag_name:
            raise ValueError("tag_required")
        tag = db.query(Tag).filter(Tag.business_id == business_id, Tag.name == tag_name).first()
        if tag is None:
            tag = Tag(business_id=business_id, name=tag_name)
            db.add(tag)
            db.flush()
        link = db.query(CustomerTag).filter(CustomerTag.business_id == business_id, CustomerTag.customer_id == conversation.customer_id, CustomerTag.tag_id == tag.id).first()
        if link is None:
            db.add(CustomerTag(business_id=business_id, customer_id=conversation.customer_id, tag_id=tag.id))
        return {"tag": tag.name, "customer_id": conversation.customer_id}
    if tool_name == "chuyen_nhan_vien":
        conversation = _conversation(db, business_id, conversation_id)
        assignee = _find_assignee(db, business_id)
        conversation.bot_mode = "human"
        if assignee:
            conversation.assigned_user_id = assignee.id
            db.add(ConversationAssignment(conversation_id=conversation.id, user_id=assignee.id, assignment_type="bot_tool"))
        record_audit(db, business_id=business_id, action="chatbot_human", resource_type="conversation", resource_id=conversation_id, metadata={"reason": args.get("reason") or "tool_call"})
        return {"bot_mode": "human", "assigned_user_id": assignee.id if assignee else None}
    if tool_name == "tao_ticket":
        ticket = route_escalation(db, business_id, conversation_id, str(args.get("description") or args.get("title") or "Yêu cầu hỗ trợ từ chatbot"))
        if ticket is None:
            conversation = _conversation(db, business_id, conversation_id)
            ticket = Ticket(business_id=business_id, customer_id=conversation.customer_id, conversation_id=conversation_id, title=str(args.get("title") or "Yêu cầu hỗ trợ"), description=str(args.get("description") or ""), priority=str(args.get("priority") or "normal"), status="open")
            db.add(ticket)
            db.flush()
        return {"ticket_id": ticket.id, "status": ticket.status, "priority": ticket.priority}
    if tool_name == "tao_don_nhap":
        conversation = _conversation(db, business_id, conversation_id)
        try:
            product_id = int(args.get("product_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("product_required") from exc
        product = db.query(Product).filter(Product.business_id == business_id, Product.id == product_id).first()
        quantity = max(int(args.get("quantity") or 1), 1)
        if product is None:
            return {"created": False, "reason": "product_not_found"}
        if quantity > _available(product):
            return {"created": False, "reason": "insufficient_stock", "available": _available(product)}
        existing = db.query(Order).filter(
            Order.business_id == business_id,
            Order.conversation_id == conversation_id,
            Order.customer_id == conversation.customer_id,
            Order.status == "draft",
        ).order_by(Order.id.desc()).first()
        if existing and any(item.product_id == product.id for item in (existing.items or [])):
            return {"created": True, "idempotent": True, "order_id": existing.id, "order_number": existing.order_number, "product_id": product.id, "quantity": quantity, "total": float(existing.total_amount or 0)}
        base = f"BOT-{conversation_id}-{product.id}"
        order_number = base
        suffix = 1
        while db.query(Order.id).filter(Order.business_id == business_id, Order.order_number == order_number).first() is not None:
            suffix += 1
            order_number = f"{base}-{suffix}"
        total = Decimal(str(product.price or 0)) * quantity
        order = Order(
            business_id=business_id,
            customer_id=conversation.customer_id,
            conversation_id=conversation_id,
            order_number=order_number,
            status="draft",
            total_amount=total,
            metadata_={"source": "chatbot_tool", "requires_staff_confirmation": True},
        )
        db.add(order)
        db.flush()
        db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=quantity, unit_price=product.price, line_total=total, product_name_snapshot=product.name, sku_snapshot=product.sku))
        return {"created": True, "order_id": order.id, "order_number": order.order_number, "product_id": product.id, "quantity": quantity, "total": float(total), "requires_confirmation": True}
    if tool_name == "dat_lich_cham_soc":
        from app.services.chatbot_followup import schedule_followup

        raw_run_at = args.get("run_at")
        if raw_run_at:
            try:
                run_at = datetime.fromisoformat(str(raw_run_at).replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("run_at_invalid") from exc
        else:
            run_at = datetime.now(timezone.utc) + timedelta(hours=2)
        row = schedule_followup(
            db,
            business_id,
            conversation_id,
            str(args.get("message") or "Shop nhắc bạn xác nhận đơn nhé."),
            run_at,
            kind=str(args.get("kind") or "custom_followup"),
            metadata={"source": "chatbot_tool"},
        )
        return {"scheduled": True, "followup_id": row.id, "run_at": row.run_at.isoformat(), "message": row.message}
    if tool_name == "dung_mau_tra_loi":
        shortcut = str(args.get("shortcut") or "").strip()
        row = db.query(CannedResponse).filter(
            CannedResponse.business_id == business_id,
            CannedResponse.shortcut == shortcut,
            CannedResponse.enabled.is_(True),
        ).first()
        if row is None:
            return {"found": False, "shortcut": shortcut}
        return {"found": True, "shortcut": row.shortcut, "title": row.title, "content": row.content}
    return {"ok": True}
