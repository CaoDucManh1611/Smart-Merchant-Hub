"""Progressive customer-profile collection for inbound sales conversations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
from threading import Thread

from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.customer_collection import (
    CustomerAddress,
    CustomerCollectionSession,
    CustomerContact,
)
from app.models.sales import Order, OrderItem, Product
from app.services.customer_collection import (
    contact_hash,
    encrypt_contact,
    mask_contact,
    normalize_contact,
)
from app.services.product_resolver import resolve_product
from app.services.notification_service import create_notification
from app.db.database import SessionLocal


REQUIRED_FIELDS = ("name", "phone", "email", "address", "payment_method")
PROMPTS = {
    "name": "Để lên đơn, bạn cho mình xin tên người nhận nhé.",
    "phone": "Bạn cho mình xin số điện thoại nhận hàng nhé.",
    "email": "Bạn cho mình xin email để gửi xác nhận đơn nhé.",
    "address": "Bạn cho mình xin địa chỉ giao hàng đầy đủ nhé.",
    "payment_method": "Bạn muốn thanh toán COD hay chuyển khoản?",
}
PAYMENT_METHODS = {
    "cod": {"cod", "thu tien khi nhan", "thanh toan khi nhan", "nhan hang moi tra"},
    "bank_transfer": {"chuyen khoan", "chuyen khoan ngan hang", "ck", "qr"},
}
GREETING_PHRASES = {
    "alo",
    "alo ban",
    "alo shop",
    "chao",
    "chao ban",
    "chao shop",
    "hello",
    "hey",
    "hi",
    "xin chao",
    "xin chao ban",
    "xin chao shop",
}
GREETING_REPLY = "Chào bạn! Mình có thể giúp bạn tìm sản phẩm hoặc tư vấn đơn hàng hôm nay nhé."
ORDER_CONFIRMATION_PHRASES = (
    "dat don",
    "chot don",
    "chot san pham",
    "chot mon",
    "chon san pham",
    "chon mon",
    "lay cai nay",
    "lay san pham nay",
    "cho minh cai nay",
    "cho toi cai nay",
    "len don",
    "xac nhan mua",
    "xac nhan don",
)
ORDER_APPROVAL_PHRASES = (
    "dong y",
    "ok",
    "oke",
    "duoc",
    "xac nhan",
    "chot",
    "dat don",
    "lay",
)
ORDER_REJECTION_PHRASES = (
    "khong",
    "huy",
    "de sau",
    "chua mua",
)
PRICE_QUERY_PHRASES = (
    "bao nhieu tien",
    "het bao nhieu",
    "tong bao nhieu",
    "thanh tien",
    "tinh tien",
    "gia bao nhieu",
    "gia cua",
    "gia nhu nao",
    "gia the nao",
)
STOCK_QUERY_PHRASES = (
    "co khong",
    "con khong",
    "con hang khong",
    "du khong",
    "co san khong",
)
GENERIC_PURCHASE_WORDS = {"hang", "do", "san", "pham"}
BROWSING_PHRASES = (
    "tim hieu",
    "danh sach san pham",
    "san pham nao",
    "gia bao nhieu",
    "tu van san pham",
    "xem san pham",
    "xem hang",
    "co san pham",
    "con san pham",
    "con hang",
    "con mau",
)
PHONE_PATTERN = re.compile(r"(?:\+?84|0)(?:[\s.-]?\d){8,10}")
EMAIL_PATTERN = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
QUANTITY_PATTERN = re.compile(r"\b(\d{1,4})\b")
PRODUCT_QUERY_STOP_WORDS = {
    "bao", "bay", "co", "cai", "cho", "gi", "gia", "het", "hang", "la",
    "mua", "nhieu", "san", "pham", "thanh", "thi", "tien", "toi", "tong",
    "muon", "vay", "xem", "voi", "so", "luong",
}


@dataclass(frozen=True)
class CollectionFlowResult:
    session_id: int
    status: str
    current_field: str | None
    prompt: str
    started: bool = False
    completed: bool = False
    draft_order_id: int | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _fold(value: str) -> str:
    # Vietnamese accents are intentionally removed only for deterministic
    # intent/payment matching; original customer text is persisted separately.
    import unicodedata
    normalized = unicodedata.normalize("NFKD", value.casefold())
    # Vietnamese đ/Đ is not decomposed by NFKD, so normalize it explicitly.
    normalized = normalized.replace("đ", "d")
    return "".join(char for char in normalized if not unicodedata.combining(char))


def is_greeting(text: str | None) -> bool:
    """Return True for a standalone greeting, not a greeting plus a request."""
    folded = _fold(str(text or ""))
    normalized = re.sub(r"[^\w\s]", " ", folded, flags=re.UNICODE)
    return " ".join(normalized.split()) in GREETING_PHRASES


def is_order_intent(text: str | None) -> bool:
    folded = _fold(str(text or ""))
    if any(phrase in folded for phrase in ORDER_CONFIRMATION_PHRASES):
        return True
    if (
        is_price_quote_request(folded)
        or is_stock_query_request(folded)
        or _looks_like_product_discovery(folded)
    ):
        return False

    # Do not start checkout for generic browsing requests such as
    # "tôi cần mua hàng". A product must follow the purchase verb.
    for marker in ("mua ", "dat hang ", "lay ", "chot "):
        marker_position = folded.find(marker)
        if marker_position < 0:
            continue
        words = folded[marker_position + len(marker):].split()
        if not words:
            continue
        if marker == "mua " and words[0] in GENERIC_PURCHASE_WORDS:
            if words[:2] == ["san", "pham"] and len(words) <= 2:
                continue
            if words[0] in {"hang", "do"}:
                continue
        if marker == "lay " and words[0] == "mon" and len(words) == 1:
            continue
        return True
    return False


def is_price_quote_request(text: str | None) -> bool:
    """Detect a quantity/price question, not a confirmed purchase."""
    folded = _fold(str(text or ""))
    return bool(QUANTITY_PATTERN.search(folded)) and any(
        phrase in folded for phrase in PRICE_QUERY_PHRASES
    )


def is_stock_query_request(text: str | None) -> bool:
    """Detect a quantity/availability question, not a confirmed purchase."""
    folded = _fold(str(text or ""))
    return bool(QUANTITY_PATTERN.search(folded)) and any(
        phrase in folded for phrase in STOCK_QUERY_PHRASES
    )


def _format_vnd(value: object) -> str:
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal("0")
    return f"{amount:,.0f}".replace(",", ".")


def _extract_quantity(text: str) -> int:
    match = QUANTITY_PATTERN.search(_fold(text))
    return int(match.group(1)) if match else 0


def _find_requested_product(
    db: Session,
    business_id: int,
    text: str,
    conversation_id: int | None = None,
) -> Product | None:
    return resolve_product(
        db,
        business_id=business_id,
        text=text,
        conversation_id=conversation_id,
    )


def _start_product_quote(
    db: Session,
    *,
    business_id: int,
    customer_id: int,
    conversation_id: int | None,
    source_channel: str,
    text: str,
) -> CollectionFlowResult:
    # A product-specific purchase without an explicit quantity is treated as
    # one item, then shown for confirmation before any customer data is asked.
    quantity = max(_extract_quantity(text), 1)
    product = _find_requested_product(db, business_id, text, conversation_id)
    if product is None:
        return CollectionFlowResult(
            session_id=0,
            status="product_not_found",
            current_field=None,
            prompt="Mình chưa tìm thấy sản phẩm bạn vừa hỏi. Bạn cho mình tên hoặc mã sản phẩm chính xác nhé.",
            started=True,
        )

    available = max(
        int(product.stock_quantity or 0) - int(product.reserved_quantity or 0),
        0,
    )
    if quantity > available:
        return CollectionFlowResult(
            session_id=0,
            status="stock_unavailable",
            current_field=None,
            prompt=(
                f"Shop hiện chỉ còn {available} {product.name}, không đủ {quantity} sản phẩm. "
                f"Bạn muốn lấy {available} sản phẩm không?"
            ),
            started=True,
        )

    total = Decimal(str(product.price or 0)) * quantity
    session = CustomerCollectionSession(
        business_id=business_id,
        customer_id=customer_id,
        conversation_id=conversation_id,
        purpose="order_confirmation",
        required_fields=["confirmation"],
        collected_fields={
            "product_id": product.id,
            "product_name": product.name,
            "quantity": quantity,
            "unit_price": str(product.price),
            "total_amount": str(total),
        },
        current_field="order_confirmation",
        source_channel=source_channel,
        status="pending",
    )
    db.add(session)
    db.flush()
    if conversation_id is not None:
        try:
            from app.services.chatbot_followup import schedule_abandoned_checkout_followup

            schedule_abandoned_checkout_followup(
                db,
                business_id=business_id,
                conversation_id=int(conversation_id),
                session_id=session.id,
                run_at=_now() + timedelta(hours=2),
            )
        except Exception:
            # A quote must still be returned when the optional scheduler is
            # unavailable (for example while a legacy DB is being migrated).
            pass
    db.commit()
    return CollectionFlowResult(
        session_id=session.id,
        status=session.status,
        current_field=session.current_field,
        prompt=(
            f"Bạn muốn mua {quantity} {product.name}. Đơn giá {_format_vnd(product.price)} đồng, "
            f"tổng cộng {_format_vnd(total)} đồng (shop còn {available}). "
            "Bạn xác nhận đặt hàng chứ?"
        ),
        started=True,
    )


def _is_order_approval(text: str | None) -> bool:
    folded = _fold(str(text or ""))
    return any(phrase in folded for phrase in ORDER_APPROVAL_PHRASES)


def _is_order_rejection(text: str | None) -> bool:
    folded = _fold(str(text or ""))
    return any(phrase in folded for phrase in ORDER_REJECTION_PHRASES)


def is_browsing_request(text: str | None) -> bool:
    """Identify product discovery messages that must stay in RAG/chat mode."""
    folded = _fold(str(text or ""))
    # A price quote is a separate flow: it must check stock and total before
    # collecting checkout details.
    if is_price_quote_request(folded) or is_stock_query_request(folded):
        return False
    if any(phrase in folded for phrase in ORDER_CONFIRMATION_PHRASES):
        return False
    # Product-discovery language wins over a generic "mua" marker, e.g.
    # "tôi muốn mua sản phẩm bạn có gì".
    if _looks_like_product_discovery(folded):
        return True
    # Everything else is left to the normal order-intent detector.
    return False


def _looks_like_product_discovery(folded: str) -> bool:
    if any(phrase in folded for phrase in BROWSING_PHRASES):
        return True
    return bool(
        re.search(r"\b(?:co|con|xem|tim|goi y|tu van|muon mua)\b.*\b(?:san pham|hang|mau)\b", folded)
        or re.search(r"\b(?:san pham|hang|mau)\b.*\b(?:gi|nao|khong)\b", folded)
        or "mua hang" in folded
    )


def _get_session(db: Session, business_id: int, customer_id: int, conversation_id: int | None):
    query = db.query(CustomerCollectionSession).filter(
        CustomerCollectionSession.business_id == business_id,
        CustomerCollectionSession.customer_id == customer_id,
        CustomerCollectionSession.status.in_(("pending", "partial")),
    )
    if conversation_id is not None:
        query = query.filter(CustomerCollectionSession.conversation_id == conversation_id)
    return query.order_by(CustomerCollectionSession.id.desc()).first()


def _cancel_checkout_reminder(
    db: Session,
    *,
    business_id: int,
    conversation_id: int | None,
    session_id: int,
) -> None:
    """Stop a quote reminder when the customer continues or changes intent."""
    if conversation_id is None:
        return
    try:
        from app.services.chatbot_followup import cancel_event_followup

        cancel_event_followup(
            db,
            business_id=business_id,
            conversation_id=int(conversation_id),
            kind="cart_abandoned",
            metadata_key="collection_session_id",
            metadata_value=session_id,
        )
    except Exception:
        # Follow-ups are optional while upgrading an older deployment.
        pass


def _ensure_email_field(session: CustomerCollectionSession) -> bool:
    """Upgrade an older pending session without changing completed sessions."""
    fields = list(session.required_fields or [])
    if "email" in fields:
        return False
    insert_at = fields.index("phone") + 1 if "phone" in fields else len(fields)
    fields.insert(insert_at, "email")
    session.required_fields = fields
    collected = dict(session.collected_fields or {})
    if not collected.get("email") and session.current_field in {None, "address", "payment_method"}:
        session.current_field = "email"
        session.status = "partial"
    return True


def _extract_value(field: str, text: str) -> str | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    folded = _fold(raw)
    if field == "name":
        value = re.sub(r"^(ten nguoi nhan|ten toi la|minh la|toi la)\s*[:,-]?\s*", "", folded and raw, flags=re.IGNORECASE).strip()
        return value[:255] if value else None
    if field == "phone":
        match = PHONE_PATTERN.search(raw)
        if not match:
            return None
        normalized = normalize_contact("phone", match.group(0))
        return normalized if len(normalized) >= 10 else None
    if field == "email":
        match = EMAIL_PATTERN.search(raw)
        if not match:
            return None
        normalized = normalize_contact("email", match.group(0))
        return normalized if 3 <= len(normalized) <= 255 else None
    if field == "address":
        return raw[:500] if len(raw) >= 5 else None
    if field == "payment_method":
        for method, values in PAYMENT_METHODS.items():
            if any(value in folded for value in values):
                return method
        return None
    return raw[:255]


def _store_contact(db: Session, *, business_id: int, customer_id: int, kind: str, value: str) -> None:
    normalized = normalize_contact(kind, value)
    value_hash = contact_hash(kind, normalized)
    existing = db.query(CustomerContact).filter(
        CustomerContact.business_id == business_id,
        CustomerContact.kind == kind,
        CustomerContact.value_hash == value_hash,
    ).first()
    if existing is not None:
        return
    db.add(CustomerContact(
        business_id=business_id,
        customer_id=customer_id,
        kind=kind,
        value_encrypted=encrypt_contact(kind, normalized),
        value_hash=value_hash,
        masked_value=mask_contact(kind, normalized),
        source="chatbot",
        confidence=0.9,
        is_primary=True,
    ))


def _store_address(db: Session, *, business_id: int, customer_id: int, value: str) -> None:
    db.add(CustomerAddress(
        business_id=business_id,
        customer_id=customer_id,
        address_line1=value[:255],
        source="chatbot",
        is_default=True,
    ))


def _chatbot_order_number(db: Session, business_id: int, session_id: int) -> str:
    """Build a readable order number that remains unique in one shop."""
    base = f"CHAT-{session_id}"
    number = base
    suffix = 1
    while db.query(Order.id).filter(
        Order.business_id == business_id,
        Order.order_number == number,
    ).first() is not None:
        suffix += 1
        number = f"{base}-{suffix}"
    return number


def _create_draft_order_for_session(
    db: Session,
    *,
    session: CustomerCollectionSession,
) -> tuple[Order | None, str | None]:
    """Turn a confirmed, product-specific collection session into one draft order.

    A generic conversation may collect contact data without a selected product.
    It deliberately remains staff-reviewed instead of producing an ambiguous order.
    """
    collected = dict(session.collected_fields or {})
    existing_id = collected.get("draft_order_id")
    if existing_id:
        existing = db.query(Order).filter(
            Order.id == int(existing_id),
            Order.business_id == session.business_id,
        ).first()
        if existing is not None:
            return existing, None

    product_id = collected.get("product_id")
    quantity = int(collected.get("quantity") or 0)
    if not product_id or quantity < 1:
        return None, "Chưa có sản phẩm cụ thể để tạo đơn nháp."

    product = db.query(Product).filter(
        Product.id == int(product_id),
        Product.business_id == session.business_id,
        Product.status == "active",
    ).first()
    if product is None:
        return None, "Sản phẩm đã ngừng bán nên cần nhân viên kiểm tra lại."

    available = max(int(product.stock_quantity or 0) - int(product.reserved_quantity or 0), 0)
    if quantity > available:
        return None, f"Sản phẩm hiện chỉ còn {available} trong kho nên cần nhân viên kiểm tra lại."

    try:
        unit_price = Decimal(str(collected.get("unit_price") or product.price))
    except (InvalidOperation, TypeError, ValueError):
        unit_price = Decimal(str(product.price or 0))
    order = Order(
        business_id=session.business_id,
        customer_id=session.customer_id,
        conversation_id=session.conversation_id,
        order_number=_chatbot_order_number(db, session.business_id, session.id),
        status="draft",
        shipping_address=collected.get("address"),
        shipping_phone=collected.get("phone"),
        total_amount=unit_price * quantity,
        metadata_={
            "source": "chatbot_collection",
            "collection_session_id": session.id,
            "payment_method": collected.get("payment_method"),
        },
    )
    db.add(order)
    db.flush()
    db.add(OrderItem(
        order_id=order.id,
        product_id=product.id,
        quantity=quantity,
        unit_price=unit_price,
        line_total=unit_price * quantity,
        product_name_snapshot=product.name,
        sku_snapshot=product.sku,
    ))
    create_notification(
        db,
        business_id=session.business_id,
        kind="chatbot_order_draft",
        title="Đơn nháp chatbot cần xác nhận",
        body=(
            f"{order.order_number}: {product.name} × {quantity} đã có đủ thông tin giao hàng. "
            "Mở Đơn bán để kiểm tra và xác nhận đơn."
        ),
        metadata={
            "order_id": order.id,
            "conversation_id": session.conversation_id,
            "customer_id": session.customer_id,
        },
    )
    collected["draft_order_id"] = order.id
    session.collected_fields = collected
    return order, None


def advance_customer_collection(
    db: Session,
    *,
    business_id: int,
    customer_id: int,
    conversation_id: int | None,
    source_channel: str,
    text: str,
) -> CollectionFlowResult | None:
    """Start or advance a collection session from one inbound chat message."""
    customer = db.query(Customer).filter(
        Customer.id == customer_id,
        Customer.business_id == business_id,
        Customer.status != "merged",
    ).first()
    if customer is None:
        return None

    session = _get_session(db, business_id, customer_id, conversation_id)
    if session is None:
        if is_price_quote_request(text) or is_stock_query_request(text):
            return _start_product_quote(
                db,
                business_id=business_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
                source_channel=source_channel,
                text=text,
            )
        if is_browsing_request(text):
            return None
        if not is_order_intent(text):
            return None
        # A product mention after a purchase intent is treated as a quote
        # first, so contact collection can only follow an explicit approval.
        if _find_requested_product(db, business_id, text, conversation_id) is not None:
            return _start_product_quote(
                db,
                business_id=business_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
                source_channel=source_channel,
                text=text,
            )
        session = CustomerCollectionSession(
            business_id=business_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            purpose="order",
            required_fields=list(REQUIRED_FIELDS),
            collected_fields={},
            current_field=REQUIRED_FIELDS[0],
            source_channel=source_channel,
            status="pending",
        )
        db.add(session)
        db.flush()
        db.commit()
        return CollectionFlowResult(
            session_id=session.id,
            status=session.status,
            current_field=session.current_field,
            prompt=PROMPTS[session.current_field],
            started=True,
        )

    # A greeting should always receive the standard greeting response. Do not
    # interpret it as a missing checkout field when an older order session is
    # still pending; the next non-greeting message can resume that session.
    if is_greeting(text):
        return None

    if is_price_quote_request(text) or is_stock_query_request(text):
        session.status = "abandoned"
        session.current_field = None
        session.last_activity_at = _now()
        _cancel_checkout_reminder(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            session_id=session.id,
        )
        db.commit()
        return _start_product_quote(
            db,
            business_id=business_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            source_channel=source_channel,
            text=text,
        )

    if session.purpose == "order_confirmation":
        quote = dict(session.collected_fields or {})
        if _is_order_rejection(text):
            session.status = "abandoned"
            session.current_field = None
            session.last_activity_at = _now()
            _cancel_checkout_reminder(
                db,
                business_id=business_id,
                conversation_id=conversation_id,
                session_id=session.id,
            )
            db.commit()
            return CollectionFlowResult(
                session_id=session.id,
                status=session.status,
                current_field=None,
                prompt="Mình đã hủy yêu cầu đặt sản phẩm này. Khi cần mua lại cứ nhắn mình nhé.",
            )
        if not _is_order_approval(text):
            return CollectionFlowResult(
                session_id=session.id,
                status=session.status,
                current_field=session.current_field,
                prompt=(
                    f"Bạn xác nhận đặt {quote.get('quantity')} {quote.get('product_name')} "
                    f"với tổng {_format_vnd(quote.get('total_amount'))} đồng chứ?"
                ),
            )
        session.purpose = "order"
        session.required_fields = list(REQUIRED_FIELDS)
        session.current_field = REQUIRED_FIELDS[0]
        session.status = "partial"
        session.last_activity_at = _now()
        _cancel_checkout_reminder(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            session_id=session.id,
        )
        db.commit()
        return CollectionFlowResult(
            session_id=session.id,
            status=session.status,
            current_field=session.current_field,
            prompt=PROMPTS[session.current_field],
        )

    if _ensure_email_field(session):
        db.commit()

    field = session.current_field
    if not field:
        return None
    if is_browsing_request(text):
        # Customers may switch back to product discovery at any checkout
        # field. Do not force the current field onto a product question;
        # leave the accepted message for RAG and let a later confirmation
        # start a fresh checkout session.
        session.status = "abandoned"
        session.current_field = None
        session.last_activity_at = _now()
        _cancel_checkout_reminder(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            session_id=session.id,
        )
        db.commit()
        return None
    value = _extract_value(field, text)
    if value is None:
        return CollectionFlowResult(
            session_id=session.id,
            status=session.status,
            current_field=field,
            prompt=PROMPTS[field],
        )

    collected = dict(session.collected_fields or {})
    collected[field] = value
    session.collected_fields = collected
    session.last_activity_at = _now()

    if field == "name" and not customer.name:
        customer.name = value
    elif field == "phone":
        _store_contact(db, business_id=business_id, customer_id=customer_id, kind="phone", value=value)
        if not customer.phone:
            customer.phone = value
    elif field == "email":
        _store_contact(db, business_id=business_id, customer_id=customer_id, kind="email", value=value)
        if not customer.email:
            customer.email = value
    elif field == "address":
        _store_address(db, business_id=business_id, customer_id=customer_id, value=value)
        if not customer.address:
            customer.address = value

    next_field = next((item for item in session.required_fields if not collected.get(item)), None)
    if next_field is not None:
        session.current_field = next_field
        session.status = "partial"
        prompt = PROMPTS[next_field]
        db.commit()
        return CollectionFlowResult(
            session_id=session.id,
            status=session.status,
            current_field=next_field,
            prompt=prompt,
        )

    session.current_field = None
    session.status = "completed"
    session.completed_at = _now()
    draft_order, draft_error = _create_draft_order_for_session(db, session=session)
    if draft_order is not None and session.conversation_id:
        try:
            from app.services.chatbot_followup import schedule_followup

            schedule_followup(
                db,
                business_id,
                int(session.conversation_id),
                "Shop nhắc bạn: đơn nháp đã sẵn sàng. Bạn có muốn xác nhận để shop lên đơn không?",
                _now() + timedelta(hours=2),
                kind="draft_order",
                metadata={"draft_order_id": draft_order.id},
            )
        except Exception:
            # Scheduling is additive; it must never block confirmation of a
            # customer order when a legacy database has not migrated yet.
            pass
    db.commit()
    if draft_order is not None:
        prompt = (
            f"Mình đã tạo đơn nháp {draft_order.order_number} cho {collected['name']}. "
            f"Phương thức thanh toán: {'COD' if collected['payment_method'] == 'cod' else 'chuyển khoản'}. "
            "Nhân viên sẽ xác nhận đơn và thông báo lại cho bạn nhé."
        )
    else:
        prompt = (
            f"Mình đã ghi nhận thông tin của {collected['name']}. "
            f"{draft_error or 'Nhân viên sẽ kiểm tra và tạo đơn cho bạn nhé.'}"
        )
    return CollectionFlowResult(
        session_id=session.id,
        status=session.status,
        current_field=None,
        prompt=prompt,
        completed=True,
        draft_order_id=draft_order.id if draft_order is not None else None,
    )


def send_collection_prompt_background(
    *,
    result: CollectionFlowResult,
    conversation_id: int,
    channel: str,
    business_id: int,
) -> None:
    """Send and persist the next collection prompt off the webhook path."""

    def worker() -> None:
        db = SessionLocal()
        try:
            # These helpers are imported lazily to avoid coupling the model
            # collection service to provider integrations during unit tests.
            from app.services.auto_reply_service import (
                _get_conversation_recipient,
                _save_auto_reply_outbound,
                _send_channel_reply,
            )

            stored_channel, recipient_id = _get_conversation_recipient(
                db,
                conversation_id,
                business_id,
            )
            meta_response = _send_channel_reply(
                db=db,
                conversation_id=conversation_id,
                channel=stored_channel,
                recipient_id=recipient_id,
                text=result.prompt,
                business_id=business_id,
            )
            _save_auto_reply_outbound(
                db=db,
                conversation_id=conversation_id,
                channel=stored_channel,
                recipient_id=recipient_id,
                external_message_id=meta_response.get("message_id"),
                content=result.prompt,
                meta_response=meta_response,
                source_document_ids=[],
            )
        except Exception:
            # The collection state is already committed. A provider outage
            # must not turn a successful inbound webhook into a 5xx response.
            import logging
            logging.getLogger(__name__).exception(
                "Customer collection prompt failed for conversation %d",
                conversation_id,
            )
        finally:
            db.close()

    Thread(
        target=worker,
        name="customer-collection-prompt",
        daemon=True,
    ).start()
