"""Progressive customer-profile collection for inbound sales conversations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
from threading import Thread

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.customer import Customer
from app.models.customer_collection import (
    CustomerAddress,
    CustomerCollectionSession,
    CustomerContact,
    CustomerVerificationChallenge,
)
from app.models.sales import Order, OrderItem, Product
from app.services.customer_collection import (
    contact_hash,
    decrypt_contact,
    encrypt_contact,
    generate_verification_code,
    hash_verification_code,
    mask_contact,
    normalize_contact,
)
from app.services.otp_delivery import (
    OtpDeliveryError,
    OtpDeliveryNotConfigured,
    deliver_otp,
)
from app.services.audit_service import record_audit
from app.services.order_service import (
    SalesOrderOperationError,
    reserve_draft_order_inventory,
    transition_sales_order,
)
from app.services.product_pricing import combo_price_comparison_reply
from app.services.product_resolver import (
    normalize_product_text,
    product_aliases,
    resolve_product_mentions,
)
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
OTP_PATTERN = re.compile(r"(?<!\d)(\d{6})(?!\d)")
OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5
CHECKOUT_CANCEL_EXACT = {
    "xoa",
    "huy",
    "cancel",
    "bo",
    "bo don",
    "khong mua",
    "khong mua nua",
    "thoi khong mua",
}
CHECKOUT_CANCEL_PHRASES = (
    "xoa don",
    "huy don",
    "bo don",
    "khong mua nua",
    "thoi khong mua",
)


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
    products = _find_requested_products(
        db,
        business_id=business_id,
        text=text,
        conversation_id=conversation_id,
    )
    return products[0] if products else None


def _find_requested_products(
    db: Session,
    *,
    business_id: int,
    text: str,
    conversation_id: int | None = None,
    allow_history: bool = True,
) -> list[Product]:
    return resolve_product_mentions(
        db,
        business_id=business_id,
        text=text,
        conversation_id=conversation_id if allow_history else None,
    )


def _product_position(text: str, product: Product) -> int | None:
    query = normalize_product_text(text)
    positions = [
        query.find(normalize_product_text(alias))
        for alias in product_aliases(product)
        if normalize_product_text(alias)
    ]
    positions = [position for position in positions if position >= 0]
    if positions:
        return min(positions)

    query_token_positions = [
        (match.group(0), match.start(), match.end())
        for match in re.finditer(r"\S+", query)
    ]
    partial_positions = []
    for alias in product_aliases(product):
        alias_tokens = [token for token in normalize_product_text(alias).split() if len(token) >= 2]
        matched = [
            item
            for token in alias_tokens
            for item in query_token_positions
            if item[0] == token
        ]
        if len({item[0] for item in matched}) >= 2:
            partial_positions.append(min(item[1] for item in matched))
    return min(partial_positions) if partial_positions else None


def _extract_quantity_for_product(text: str, product: Product, product_count: int) -> int:
    """Extract a quantity attached to one product in a multi-item message."""
    if product_count <= 1:
        return max(_extract_quantity(text), 1)

    query = normalize_product_text(text)
    position = _product_position(text, product)
    if position is None:
        return 1
    prefix = query[max(0, position - 40):position]
    match = re.search(
        r"(\d{1,4})(?:\s+(?:cai|bo|sp|san pham))?\s*$",
        prefix,
    )
    return max(int(match.group(1)), 1) if match else 1


def _quote_items(collected: dict) -> list[dict]:
    """Read the new multi-item shape while supporting legacy one-item sessions."""
    raw_items = collected.get("items")
    if isinstance(raw_items, list):
        items = [dict(item) for item in raw_items if isinstance(item, dict) and item.get("product_id")]
        if items:
            return items
    product_id = collected.get("product_id")
    if not product_id:
        return []
    return [{
        "product_id": int(product_id),
        "product_name": collected.get("product_name") or "Sản phẩm",
        "quantity": max(int(collected.get("quantity") or 1), 1),
        "unit_price": str(collected.get("unit_price") or "0"),
        "available": collected.get("available"),
    }]


def _set_quote_items(collected: dict, items: list[dict]) -> Decimal:
    total = sum(
        Decimal(str(item.get("unit_price") or 0)) * max(int(item.get("quantity") or 1), 1)
        for item in items
    )
    collected["items"] = items
    if items:
        first = items[0]
        # Keep the original keys for old sessions/API consumers while the
        # ``items`` array carries the complete cart.
        collected.update({
            "product_id": first.get("product_id"),
            "product_name": first.get("product_name"),
            "quantity": first.get("quantity"),
            "unit_price": first.get("unit_price"),
        })
    collected["total_amount"] = str(total)
    return total


def _refresh_quote_stock(db: Session, business_id: int, items: list[dict]) -> None:
    """Refresh availability for legacy and long-lived pending quotes."""
    product_ids = [int(item["product_id"]) for item in items if item.get("product_id")]
    if not product_ids:
        return
    products = db.query(Product).filter(
        Product.business_id == business_id,
        Product.id.in_(product_ids),
    ).all()
    by_id = {product.id: product for product in products}
    for item in items:
        product = by_id.get(int(item["product_id"]))
        if product is None:
            item["available"] = 0
            continue
        item["available"] = max(
            int(product.stock_quantity or 0) - int(product.reserved_quantity or 0),
            0,
        )


def _format_quote_prompt(items: list[dict]) -> str:
    if len(items) == 1:
        item = items[0]
        total = Decimal(str(item.get("unit_price") or 0)) * int(item.get("quantity") or 1)
        return (
            f"Bạn muốn mua {int(item.get('quantity') or 1)} {item.get('product_name')}. "
            f"Đơn giá {_format_vnd(item.get('unit_price'))} đồng, tổng cộng {_format_vnd(total)} đồng "
            f"(shop còn {item.get('available', 0)}). Bạn xác nhận đặt hàng chứ?"
        )

    product_parts = [
        f"{int(item.get('quantity') or 1)} {item.get('product_name')} "
        f"({_format_vnd(item.get('unit_price'))} đồng/cái)"
        for item in items
    ]
    if len(product_parts) == 2:
        product_text = " và ".join(product_parts)
    else:
        product_text = ", ".join(product_parts[:-1]) + f" và {product_parts[-1]}"
    total = sum(
        Decimal(str(item.get("unit_price") or 0)) * int(item.get("quantity") or 1)
        for item in items
    )
    stock_text = ", ".join(
        f"{item.get('product_name')}: còn {item.get('available', 0)}"
        for item in items
    )
    return (
        f"Bạn muốn mua {product_text}. Tổng cộng {_format_vnd(total)} đồng "
        f"({stock_text}). Bạn xác nhận đặt hàng chứ?"
    )


def _stock_unavailable_prompt(items: list[dict]) -> str:
    shortages = [
        f"{item.get('product_name')} chỉ còn {item.get('available', 0)} "
        f"(bạn chọn {int(item.get('quantity') or 1)})"
        for item in items
        if int(item.get("quantity") or 1) > int(item.get("available") or 0)
    ]
    if len(items) == 1 and shortages:
        item = items[0]
        return (
            f"Shop hiện chỉ còn {item.get('available', 0)} {item.get('product_name')}, "
            f"không đủ {int(item.get('quantity') or 1)} sản phẩm. Bạn muốn lấy "
            f"{item.get('available', 0)} sản phẩm không?"
        )
    return "Shop chưa đủ hàng: " + "; ".join(shortages) + ". Bạn giảm số lượng hoặc chọn sản phẩm khác nhé."


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
    # Resolve every product mention so a single message can start a cart with
    # multiple lines instead of silently keeping only the best match.
    products = _find_requested_products(
        db,
        business_id=business_id,
        text=text,
        conversation_id=conversation_id,
    )
    if not products:
        return CollectionFlowResult(
            session_id=0,
            status="product_not_found",
            current_field=None,
            prompt="Mình chưa tìm thấy sản phẩm bạn vừa hỏi. Bạn cho mình tên hoặc mã sản phẩm chính xác nhé.",
            started=True,
        )

    items: list[dict] = []
    for product in products:
        quantity = _extract_quantity_for_product(text, product, len(products))
        available = max(
            int(product.stock_quantity or 0) - int(product.reserved_quantity or 0),
            0,
        )
        items.append({
            "product_id": product.id,
            "product_name": product.name,
            "quantity": quantity,
            "unit_price": str(product.price),
            "available": available,
        })

    if any(int(item["quantity"]) > int(item["available"]) for item in items):
        return CollectionFlowResult(
            session_id=0,
            status="stock_unavailable",
            current_field=None,
            prompt=_stock_unavailable_prompt(items),
            started=True,
        )

    collected = {}
    total = _set_quote_items(collected, items)
    session = CustomerCollectionSession(
        business_id=business_id,
        customer_id=customer_id,
        conversation_id=conversation_id,
        purpose="order_confirmation",
        required_fields=["confirmation"],
        collected_fields=collected,
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
        prompt=_format_quote_prompt(items),
        started=True,
    )


def _is_order_approval(text: str | None) -> bool:
    folded = _fold(str(text or ""))
    return any(phrase in folded for phrase in ORDER_APPROVAL_PHRASES)


def _is_order_rejection(text: str | None) -> bool:
    folded = _fold(str(text or ""))
    return any(phrase in folded for phrase in ORDER_REJECTION_PHRASES)


def _is_product_switch_request(text: str | None) -> bool:
    """Detect a rejection that immediately names the product to keep."""
    folded = _fold(str(text or ""))
    return (
        any(phrase in folded for phrase in ("muon mua", "chi mua", "doi sang", "thay bang"))
        and "mua them" not in folded
        and "them " not in folded
    )


def _is_checkout_cancel_request(text: str | None) -> bool:
    """Recognize a deliberate cancellation while a draft is awaiting OTP.

    The collection state is checked before the normal order router, so short
    customer messages such as ``xóa`` must be handled here instead of being
    interpreted as an invalid OTP and receiving the same stale prompt again.
    """
    folded = " ".join(_fold(str(text or "")).split())
    return folded in CHECKOUT_CANCEL_EXACT or any(
        phrase in folded for phrase in CHECKOUT_CANCEL_PHRASES
    )


def _is_fresh_checkout_request(
    db: Session,
    *,
    business_id: int,
    conversation_id: int | None,
    text: str | None,
) -> bool:
    """Tell a new purchase apart from an OTP reply for the old draft."""
    if is_order_intent(text) or is_browsing_request(text):
        return True
    # Do not use conversation history for this check: an old product mention
    # must not turn a six-digit OTP or a generic message into a new order.
    return bool(_find_requested_products(
        db,
        business_id=business_id,
        text=str(text or ""),
        conversation_id=conversation_id,
        allow_history=False,
    ))


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


def _has_specific_purchase_signal(text: str | None) -> bool:
    """Return true when the message explicitly asks to buy a named item.

    Generic discovery messages also contain ``muốn mua`` (for example,
    ``tôi muốn mua sản phẩm bạn có gì``). They must stay on the catalogue
    route, while a resolved product name should start a deterministic quote.
    """
    folded = " ".join(_fold(str(text or "")).split())
    return bool(re.search(r"\b(?:mua|dat|lay|chot)\b", folded))


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
        CustomerCollectionSession.status.in_(("pending", "partial", "completed")),
    )
    if conversation_id is not None:
        query = query.filter(CustomerCollectionSession.conversation_id == conversation_id)
    # Completed sessions are normally terminal.  Keep only the two explicit
    # post-draft states so an old completed profile does not hijack a new chat.
    for row in query.order_by(CustomerCollectionSession.id.desc()).all():
        fields = row.collected_fields or {}
        if row.status != "completed" or fields.get("otp_pending") or fields.get("awaiting_customer_confirmation"):
            return row
    return None


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
        # Reusing a contact from the same customer should also restore its
        # primary flag.  A previous order may have made another value the
        # primary contact; leaving the reused value demoted would make the
        # Customer 360 projection appear inconsistent.
        if existing.customer_id == customer_id:
            db.query(CustomerContact).filter(
                CustomerContact.business_id == business_id,
                CustomerContact.customer_id == customer_id,
                CustomerContact.kind == kind,
                CustomerContact.id != existing.id,
                CustomerContact.is_primary.is_(True),
            ).update({CustomerContact.is_primary: False}, synchronize_session=False)
            existing.is_primary = True
        return
    # Keep one primary contact per type while retaining prior values for
    # history/audit.  Customer 360 can therefore project the newest primary
    # without rendering every historical entry in the compact card.
    db.query(CustomerContact).filter(
        CustomerContact.business_id == business_id,
        CustomerContact.customer_id == customer_id,
        CustomerContact.kind == kind,
        CustomerContact.is_primary.is_(True),
    ).update({CustomerContact.is_primary: False}, synchronize_session=False)
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
    normalized = " ".join(str(value or "").split()).strip()
    existing = db.query(CustomerAddress).filter(
        CustomerAddress.business_id == business_id,
        CustomerAddress.customer_id == customer_id,
        CustomerAddress.address_line1 == normalized[:255],
    ).first()
    if existing is not None:
        existing.is_default = True
        db.query(CustomerAddress).filter(
            CustomerAddress.business_id == business_id,
            CustomerAddress.customer_id == customer_id,
            CustomerAddress.id != existing.id,
        ).update({CustomerAddress.is_default: False}, synchronize_session=False)
        return
    db.query(CustomerAddress).filter(
        CustomerAddress.business_id == business_id,
        CustomerAddress.customer_id == customer_id,
        CustomerAddress.is_default.is_(True),
    ).update({CustomerAddress.is_default: False}, synchronize_session=False)
    db.add(CustomerAddress(
        business_id=business_id,
        customer_id=customer_id,
        address_line1=normalized[:255],
        source="chatbot",
        is_default=True,
    ))


def _checkout_otp_prompt(
    order: Order,
    *,
    follow_up: bool = False,
    delivery_pending: bool = False,
    delivery_channels: list[str] | None = None,
    demo_codes: list[str] | None = None,
) -> str:
    prefix = "Mã OTP chưa đúng hoặc đã hết hiệu lực. " if follow_up else ""
    channels = list(delivery_channels or [])
    if delivery_pending and not channels:
        delivery_hint = " Hiện chưa gửi OTP thành công; bạn thử lại sau ít phút hoặc liên hệ nhân viên nhé."
    elif delivery_pending:
        delivery_hint = " Shop đang gửi lại mã, bạn chờ một chút rồi nhập mã nhận được nhé."
    elif channels == ["email"]:
        delivery_hint = " Mã đã được gửi qua email bạn cung cấp."
    elif channels == ["sms"]:
        delivery_hint = " Mã đã được gửi qua số điện thoại bạn cung cấp."
    elif channels:
        delivery_hint = " Mã đã được gửi qua email và số điện thoại bạn cung cấp."
    else:
        delivery_hint = ""
    demo_hint = ""
    if demo_codes:
        # This branch is guarded by OTP_DELIVERY_MODE=in_chat, which is
        # rejected in production.  It gives a zero-cost local demo a usable
        # OTP without persisting the raw value or writing it to audit logs.
        demo_hint = "\n[DEMO] Mã OTP trong cuộc trò chuyện: " + ", ".join(demo_codes) + "."
    delivery_text = (
        "Hiện chưa gửi OTP thành công."
        if delivery_pending and not channels
        else "Shop đã gửi mã OTP 6 số đến thông tin liên hệ bạn cung cấp."
    )
    return (
        f"{prefix}Mình đã tạo đơn nháp {order.order_number}. "
        f"{delivery_text}{delivery_hint}{demo_hint} "
        "Bạn nhập mã OTP để xác thực trước khi xác nhận đơn nhé."
    )


def _create_checkout_otp_challenges(
    db: Session,
    *,
    session: CustomerCollectionSession,
    order: Order,
) -> bool:
    """Create short-lived contact challenges after a draft exists.

    The raw code is deliberately never persisted, returned or written to the
    audit stream.  A tenant can plug an SMS/email provider into the
    ``status=sent`` hand-off later; the chat flow already enforces the same
    state transition in development and production.
    """
    collected = dict(session.collected_fields or {})
    challenge_ids = [int(value) for value in (collected.get("otp_challenge_ids") or []) if str(value).isdigit()]
    if collected.get("otp_pending") and challenge_ids:
        return True

    verified_kinds: list[str] = []
    new_challenge_ids: list[int] = []
    delivery_pending = False
    demo_codes: list[str] = []
    delivered_channels: list[str] = []
    now = _now()
    delivery_mode = settings.OTP_DELIVERY_MODE.strip().lower()
    if delivery_mode == "smtp":
        challenge_channels = (("email", "email"),)
    elif delivery_mode == "twilio":
        challenge_channels = (("phone", "sms"),)
    else:
        # disabled/in_chat are local demo modes; retain both channels so the
        # full verification state machine remains testable without a provider.
        challenge_channels = (("phone", "sms"), ("email", "email"))
    for kind, channel in challenge_channels:
        value = collected.get(kind)
        if not value:
            continue
        contact = db.query(CustomerContact).filter(
            CustomerContact.business_id == session.business_id,
            CustomerContact.customer_id == session.customer_id,
            CustomerContact.kind == kind,
            CustomerContact.value_hash == contact_hash(kind, value),
        ).first()
        if contact is None:
            continue
        if contact.verification_status == "verified":
            verified_kinds.append(kind)
            continue
        code = generate_verification_code()
        challenge = CustomerVerificationChallenge(
            business_id=session.business_id,
            customer_id=session.customer_id,
            contact_id=contact.id,
            channel=channel,
            code_hash=hash_verification_code(code),
            status="queued",
            attempts=0,
            max_attempts=OTP_MAX_ATTEMPTS,
            expires_at=now + OTP_TTL,
        )
        contact.verification_status = "pending"
        db.add(challenge)
        db.flush()
        new_challenge_ids.append(challenge.id)
        try:
            destination = decrypt_contact(kind, contact.value_encrypted)
            delivery = deliver_otp(channel=channel, destination=destination, code=code)
            # Disabled delivery is the intentional local/demo mode.  Treat it
            # as accepted so the state machine remains fully testable; real
            # providers only reach this branch after a successful send.
            if delivery.delivered or delivery.provider == "disabled":
                challenge.status = "sent"
                delivered_channels.append(channel)
                if delivery.provider == "in_chat":
                    demo_codes.append(f"{channel} {code}")
            else:
                delivery_pending = True
        except (OtpDeliveryNotConfigured, OtpDeliveryError, ValueError, OSError) as error:
            # Keep the challenge queued for a bounded retry/re-send path and
            # never fail the order draft because an external provider is down.
            delivery_pending = True
            record_audit(
                db,
                business_id=session.business_id,
                actor_type="system",
                action="verification_delivery_failed",
                resource_type="customer_contact",
                resource_id=contact.id,
                correlation_id=f"checkout:{session.id}",
                metadata={"channel": channel, "error_type": type(error).__name__},
            )
        record_audit(
            db,
            business_id=session.business_id,
            actor_type="bot",
            action="checkout_otp_requested",
            resource_type="customer_contact",
            resource_id=contact.id,
            correlation_id=f"checkout:{session.id}",
            metadata={"customer_id": session.customer_id, "channel": channel, "expires_at": challenge.expires_at.isoformat()},
        )

    collected["otp_challenge_ids"] = new_challenge_ids
    collected["otp_verified_kinds"] = verified_kinds
    collected["otp_pending"] = bool(new_challenge_ids)
    collected["otp_delivery_pending"] = delivery_pending
    collected["otp_delivery_channels"] = delivered_channels
    collected["awaiting_customer_confirmation"] = not bool(new_challenge_ids)
    order_metadata = dict(order.metadata_ or {})
    order_metadata["contact_verification_pending"] = bool(new_challenge_ids)
    order_metadata["otp_challenge_ids"] = new_challenge_ids
    order.metadata_ = order_metadata
    session.collected_fields = collected
    # Keep demo-only codes transient on this request object.  They are added
    # to the immediate in-chat prompt but are never persisted in session JSON.
    # The prompt itself is user-visible demo data; production rejects this
    # transport because chat history is not a secure OTP channel.
    setattr(session, "_otp_demo_codes", demo_codes)
    return bool(new_challenge_ids)


def _extract_otp(text: str | None) -> str | None:
    match = OTP_PATTERN.search(str(text or ""))
    return match.group(1) if match else None


def _advance_checkout_verification(
    db: Session,
    *,
    session: CustomerCollectionSession,
    text: str,
) -> CollectionFlowResult:
    """Consume one OTP and unlock the customer-confirmation state."""
    collected = dict(session.collected_fields or {})
    order_id = collected.get("draft_order_id")
    order = db.query(Order).filter(
        Order.id == int(order_id or 0),
        Order.business_id == session.business_id,
        Order.customer_id == session.customer_id,
    ).first()
    if order is None:
        collected["otp_pending"] = False
        session.collected_fields = collected
        db.commit()
        return CollectionFlowResult(
            session_id=session.id,
            status=session.status,
            current_field=None,
            prompt="Đơn nháp không còn tồn tại. Nhân viên sẽ kiểm tra lại giúp bạn nhé.",
        )

    challenge_ids = [int(value) for value in (collected.get("otp_challenge_ids") or []) if str(value).isdigit()]
    challenges = db.query(CustomerVerificationChallenge).filter(
        CustomerVerificationChallenge.id.in_(challenge_ids or [0]),
        CustomerVerificationChallenge.business_id == session.business_id,
        CustomerVerificationChallenge.customer_id == session.customer_id,
    ).order_by(CustomerVerificationChallenge.id.asc()).all()
    active = [row for row in challenges if row.status not in {"verified", "locked", "expired"}]
    if not active:
        collected["otp_pending"] = False
        collected["awaiting_customer_confirmation"] = True
        session.collected_fields = collected
        metadata = dict(order.metadata_ or {})
        metadata["contact_verification_pending"] = False
        order.metadata_ = metadata
        db.commit()
        return CollectionFlowResult(
            session_id=session.id,
            status=session.status,
            current_field=None,
            prompt="Thông tin liên hệ đã xác thực. Bạn xác nhận chốt đơn này chứ?",
        )

    code = _extract_otp(text)
    if code is None:
        return CollectionFlowResult(
            session_id=session.id,
            status=session.status,
            current_field=None,
            prompt=_checkout_otp_prompt(
                order,
                delivery_pending=bool(collected.get("otp_delivery_pending")),
                delivery_channels=list(collected.get("otp_delivery_channels") or []),
            ),
        )

    challenge = active[0]
    now = _now()
    if challenge.expires_at < now:
        challenge.status = "expired"
        db.commit()
        return CollectionFlowResult(
            session_id=session.id,
            status=session.status,
            current_field=None,
            prompt="Mã OTP đã hết hạn. Bạn liên hệ nhân viên để được gửi lại mã nhé.",
        )
    challenge.attempts += 1
    # Compare hashes only; the submitted code is never persisted.
    import hmac
    if not hmac.compare_digest(hash_verification_code(code), challenge.code_hash):
        if challenge.attempts >= challenge.max_attempts:
            challenge.status = "locked"
        db.commit()
        return CollectionFlowResult(
            session_id=session.id,
            status=session.status,
            current_field=None,
            prompt=(
                "Mã OTP đã bị khóa do nhập sai quá số lần. Bạn liên hệ nhân viên để được hỗ trợ nhé."
                if challenge.status == "locked" else _checkout_otp_prompt(
                    order,
                    follow_up=True,
                    delivery_pending=bool(collected.get("otp_delivery_pending")),
                    delivery_channels=list(collected.get("otp_delivery_channels") or []),
                )
            ),
        )

    challenge.status = "verified"
    challenge.verified_at = now
    contact = db.get(CustomerContact, challenge.contact_id)
    if contact is not None and contact.business_id == session.business_id and contact.customer_id == session.customer_id:
        contact.verification_status = "verified"
        contact.verified_at = now
        verified_kinds = list(collected.get("otp_verified_kinds") or [])
        if contact.kind not in verified_kinds:
            verified_kinds.append(contact.kind)
        collected["otp_verified_kinds"] = verified_kinds
    remaining = [row for row in active[1:] if row.status != "verified"]
    collected["otp_pending"] = bool(remaining)
    collected["awaiting_customer_confirmation"] = not bool(remaining)
    metadata = dict(order.metadata_ or {})
    metadata["contact_verification_pending"] = bool(remaining)
    metadata["contact_verified_at"] = now.isoformat()
    order.metadata_ = metadata
    session.collected_fields = collected
    record_audit(
        db,
        business_id=session.business_id,
        actor_type="customer",
        action="checkout_otp_verified",
        resource_type="customer_contact",
        resource_id=challenge.contact_id,
        correlation_id=f"checkout:{session.id}",
        metadata={"customer_id": session.customer_id, "challenge_id": challenge.id},
    )
    db.commit()
    if remaining:
        return CollectionFlowResult(
            session_id=session.id,
            status=session.status,
            current_field=None,
            prompt="Số điện thoại đã xác thực. Bạn nhập OTP email còn lại để tiếp tục nhé.",
        )
    return CollectionFlowResult(
        session_id=session.id,
        status=session.status,
        current_field=None,
        prompt=f"Thông tin liên hệ đã xác thực cho đơn nháp {order.order_number}. Bạn xác nhận chốt đơn này chứ?",
    )


def _cancel_pending_checkout(
    db: Session,
    *,
    session: CustomerCollectionSession,
    reason: str,
) -> CollectionFlowResult:
    """Cancel an OTP-pending draft and make the collection state terminal.

    A pending OTP is tied to one draft order.  Leaving that session active
    after the customer says ``xóa`` causes every later message to be routed
    back to the old OTP prompt and leaves stock reserved indefinitely.  This
    helper closes both sides atomically while retaining the session/order for
    audit history.
    """
    collected = dict(session.collected_fields or {})
    order_id = collected.get("draft_order_id")
    order = db.query(Order).filter(
        Order.id == int(order_id or 0),
        Order.business_id == session.business_id,
        Order.customer_id == session.customer_id,
    ).first()

    if order is not None and order.status in {"draft", "confirmed"}:
        try:
            transition_sales_order(
                db,
                order_id=order.id,
                to_status="cancelled",
                actor_id=None,
                business_id=session.business_id,
            )
            order.cancel_reason = reason[:2000]
        except SalesOrderOperationError:
            # A staff member may have transitioned the order concurrently.
            # The stale customer-collection state must still be closed; the
            # audit record lets staff reconcile that exceptional case.
            record_audit(
                db,
                business_id=session.business_id,
                actor_type="bot",
                action="checkout_cancel_failed",
                resource_type="sales_order",
                resource_id=order.id,
                correlation_id=f"checkout:{session.id}",
                metadata={"reason": reason[:500]},
            )

    challenge_ids = [
        int(value)
        for value in (collected.get("otp_challenge_ids") or [])
        if str(value).isdigit()
    ]
    challenges = db.query(CustomerVerificationChallenge).filter(
        CustomerVerificationChallenge.id.in_(challenge_ids or [0]),
        CustomerVerificationChallenge.business_id == session.business_id,
        CustomerVerificationChallenge.customer_id == session.customer_id,
    ).all()
    for challenge in challenges:
        if challenge.status not in {"verified", "locked", "expired"}:
            challenge.status = "expired"
        contact = db.get(CustomerContact, challenge.contact_id)
        if contact is not None and contact.verification_status == "pending":
            other_active = db.query(CustomerVerificationChallenge.id).filter(
                CustomerVerificationChallenge.contact_id == contact.id,
                CustomerVerificationChallenge.id != challenge.id,
                CustomerVerificationChallenge.status.in_({"queued", "sent"}),
            ).first()
            if other_active is None:
                contact.verification_status = "unverified"

    collected.update({
        "otp_pending": False,
        "otp_delivery_pending": False,
        "awaiting_customer_confirmation": False,
        "confirmation_status": "cancelled",
        "cancelled_at": _now().isoformat(),
    })
    session.collected_fields = collected
    session.status = "abandoned"
    session.current_field = None
    session.last_activity_at = _now()
    if session.conversation_id is not None:
        _cancel_checkout_reminder(
            db,
            business_id=session.business_id,
            conversation_id=session.conversation_id,
            session_id=session.id,
        )
    if order is not None:
        record_audit(
            db,
            business_id=session.business_id,
            actor_type="customer",
            action="checkout_cancelled",
            resource_type="sales_order",
            resource_id=order.id,
            correlation_id=f"checkout:{session.id}",
            metadata={
                "customer_id": session.customer_id,
                "conversation_id": session.conversation_id,
                "reason": reason[:500],
            },
        )
    db.commit()
    order_number = order.order_number if order is not None else "đơn nháp"
    return CollectionFlowResult(
        session_id=session.id,
        status=session.status,
        current_field=None,
        prompt=f"Mình đã hủy đơn nháp {order_number} theo yêu cầu của bạn và giải phóng tồn kho. Khi cần mua lại cứ nhắn mình nhé.",
        draft_order_id=order.id if order is not None else None,
    )


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

    quote_items = _quote_items(collected)
    if not quote_items:
        return None, "Chưa có sản phẩm cụ thể để tạo đơn nháp."

    validated_items: list[tuple[Product, int, Decimal]] = []
    for raw_item in quote_items:
        product = db.query(Product).filter(
            Product.id == int(raw_item.get("product_id")),
            Product.business_id == session.business_id,
            Product.status == "active",
        ).first()
        if product is None:
            return None, "Sản phẩm đã ngừng bán nên cần nhân viên kiểm tra lại."

        quantity = max(int(raw_item.get("quantity") or 1), 1)
        available = max(int(product.stock_quantity or 0) - int(product.reserved_quantity or 0), 0)
        if quantity > available:
            return None, f"Sản phẩm {product.name} hiện chỉ còn {available} trong kho nên cần nhân viên kiểm tra lại."

        try:
            unit_price = Decimal(str(raw_item.get("unit_price") or product.price))
        except (InvalidOperation, TypeError, ValueError):
            unit_price = Decimal(str(product.price or 0))
        validated_items.append((product, quantity, unit_price))

    total = sum(unit_price * quantity for _product, quantity, unit_price in validated_items)
    order = Order(
        business_id=session.business_id,
        customer_id=session.customer_id,
        conversation_id=session.conversation_id,
        order_number=_chatbot_order_number(db, session.business_id, session.id),
        status="draft",
        shipping_address=collected.get("address"),
        shipping_phone=collected.get("phone"),
        total_amount=total,
        metadata_={
            "source": "chatbot_collection",
            "collection_session_id": session.id,
            "payment_method": collected.get("payment_method"),
            "items": [
                {
                    "product_id": product.id,
                    "quantity": quantity,
                    "unit_price": str(unit_price),
                }
                for product, quantity, unit_price in validated_items
            ],
        },
    )
    db.add(order)
    db.flush()
    for product, quantity, unit_price in validated_items:
        db.add(OrderItem(
            order_id=order.id,
            product_id=product.id,
            quantity=quantity,
            unit_price=unit_price,
            line_total=unit_price * quantity,
            product_name_snapshot=product.name,
            sku_snapshot=product.sku,
        ))
    db.flush()
    try:
        reserve_draft_order_inventory(
            db,
            order=order,
            business_id=session.business_id,
        )
    except SalesOrderOperationError as exc:
        # A concurrent sale may consume stock after the quote was shown. Do
        # not leave an unreserved orphan draft behind; the caller can safely
        # explain the current stock state and let the customer retry.
        db.delete(order)
        db.flush()
        return None, exc.detail
    item_summary = ", ".join(
        f"{product.name} × {quantity}"
        for product, quantity, _unit_price in validated_items
    )
    create_notification(
        db,
        business_id=session.business_id,
        kind="chatbot_order_draft",
        title="Đơn nháp chatbot cần xác nhận",
        body=(
            f"{order.order_number}: {item_summary} đã có đủ thông tin giao hàng. "
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
        combo_reply = combo_price_comparison_reply(
            db,
            business_id=business_id,
            text=text,
            conversation_id=conversation_id,
        )
        if combo_reply:
            return CollectionFlowResult(
                session_id=0,
                status="catalog_answer",
                current_field=None,
                prompt=combo_reply,
            )
        if is_price_quote_request(text) or is_stock_query_request(text):
            return _start_product_quote(
                db,
                business_id=business_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
                source_channel=source_channel,
                text=text,
            )
        # Resolve an explicitly named product before the generic browsing
        # detector. Otherwise ``muốn mua 3 Kem chống nắng ...`` is mistaken
        # for a catalogue request and the bot repeats every product.
        if _has_specific_purchase_signal(text) and _find_requested_product(
            db,
            business_id,
            text,
            conversation_id=None,
        ) is not None:
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
        # Preserve the existing quote-first behavior for a product mention
        # that uses an order-confirmation phrase rather than a purchase verb.
        if _find_requested_product(db, business_id, text, conversation_id=None) is not None:
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

    # A draft is not customer-confirmed until the contact challenge succeeds.
    # This branch intentionally runs before product/RAG handling so a six-digit
    # OTP cannot be mistaken for a quantity or a generic question.
    collected_state = dict(session.collected_fields or {})
    if collected_state.get("otp_pending"):
        if _is_checkout_cancel_request(text):
            return _cancel_pending_checkout(
                db,
                session=session,
                reason="Khách yêu cầu hủy đơn nháp trong lúc xác thực OTP",
            )
        # A customer who starts a new purchase while an old OTP is pending is
        # not answering that OTP. Close the old draft first, then route the
        # new product request through the normal quote flow. Generic product
        # discovery is returned to RAG so it can show the current catalogue.
        if _is_fresh_checkout_request(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            text=text,
        ):
            _cancel_pending_checkout(
                db,
                session=session,
                reason="Khách bắt đầu yêu cầu mua mới khi đơn cũ đang chờ OTP",
            )
            if is_browsing_request(text) and not is_order_intent(text) and not _find_requested_products(
                db,
                business_id=business_id,
                text=str(text or ""),
                conversation_id=conversation_id,
                allow_history=False,
            ):
                return None
            return advance_customer_collection(
                db,
                business_id=business_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
                source_channel=source_channel,
                text=text,
            )
        # Every other message is an answer to the active OTP challenge.  New
        # product/browsing requests were handled above by
        # ``_is_fresh_checkout_request``; short approval text such as
        # ``xác nhận`` must not be dropped merely because it is not an order
        # intent on its own.
        return _advance_checkout_verification(db, session=session, text=text)

    combo_reply = combo_price_comparison_reply(
        db,
        business_id=business_id,
        text=text,
        conversation_id=conversation_id,
    )
    if combo_reply:
        return CollectionFlowResult(
            session_id=session.id,
            status=session.status,
            current_field=session.current_field,
            prompt=combo_reply,
        )

    if collected_state.get("awaiting_customer_confirmation"):
        order_id = collected_state.get("draft_order_id")
        order = db.query(Order).filter(
            Order.id == int(order_id or 0),
            Order.business_id == business_id,
            Order.customer_id == customer_id,
        ).first()
        if order is None:
            session.collected_fields = {**collected_state, "awaiting_customer_confirmation": False}
            db.commit()
            return CollectionFlowResult(
                session_id=session.id,
                status=session.status,
                current_field=None,
                prompt="Đơn nháp không còn tồn tại. Nhân viên sẽ kiểm tra lại giúp bạn nhé.",
            )
        if order.metadata_ and order.metadata_.get("customer_confirmed"):
            return CollectionFlowResult(
                session_id=session.id,
                status=session.status,
                current_field=None,
                prompt=f"Đơn nháp {order.order_number} đã được bạn xác nhận. Nhân viên sẽ tạo đơn chính thức nhé.",
                completed=True,
                draft_order_id=order.id,
            )
        if _is_order_rejection(text):
            metadata = dict(order.metadata_ or {})
            metadata["customer_confirmed"] = False
            metadata["customer_declined_at"] = _now().isoformat()
            order.metadata_ = metadata
            session.status = "abandoned"
            session.collected_fields = {**collected_state, "awaiting_customer_confirmation": False, "confirmation_status": "declined"}
            session.last_activity_at = _now()
            db.commit()
            return CollectionFlowResult(
                session_id=session.id,
                status=session.status,
                current_field=None,
                prompt="Mình đã giữ đơn nháp ở trạng thái chưa xác nhận. Khi cần mua lại cứ nhắn mình nhé.",
                draft_order_id=order.id,
            )
        if not _is_order_approval(text):
            return CollectionFlowResult(
                session_id=session.id,
                status=session.status,
                current_field=None,
                prompt=f"Bạn xác nhận chốt đơn nháp {order.order_number} chứ?",
                draft_order_id=order.id,
            )
        metadata = dict(order.metadata_ or {})
        metadata["customer_confirmed"] = True
        metadata["customer_confirmed_at"] = _now().isoformat()
        order.metadata_ = metadata
        session.collected_fields = {**collected_state, "awaiting_customer_confirmation": False, "confirmation_status": "customer_confirmed"}
        session.last_activity_at = _now()
        record_audit(
            db,
            business_id=business_id,
            actor_type="customer",
            action="checkout_customer_confirmed",
            resource_type="sales_order",
            resource_id=order.id,
            correlation_id=f"checkout:{session.id}",
            metadata={"conversation_id": conversation_id, "customer_id": customer_id},
        )
        create_notification(
            db,
            business_id=business_id,
            kind="chatbot_order_customer_confirmed",
            title="Khách đã xác nhận đơn nháp",
            body=f"{order.order_number}: khách đã xác thực liên hệ và xác nhận. Nhân viên kiểm tra để tạo đơn chính thức.",
            metadata={"order_id": order.id, "conversation_id": conversation_id, "customer_id": customer_id},
        )
        db.commit()
        return CollectionFlowResult(
            session_id=session.id,
            status=session.status,
            current_field=None,
            prompt=f"Mình đã ghi nhận bạn xác nhận đơn nháp {order.order_number}. Nhân viên sẽ tạo đơn chính thức và báo lại cho bạn nhé.",
            completed=True,
            draft_order_id=order.id,
        )

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
        # A customer may add another product while reviewing the quote.  Do
        # this before checking approval so a message such as “mua thêm 1
        # serum” updates the same cart instead of repeating the old quote.
        items = _quote_items(quote)
        _refresh_quote_stock(db, business_id, items)
        additional_products = _find_requested_products(
            db,
            business_id=business_id,
            text=text,
            conversation_id=conversation_id,
            allow_history=False,
        )
        is_switch = bool(additional_products and _is_product_switch_request(text))
        if _is_order_rejection(text) and not is_switch:
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
        if additional_products:
            if is_switch:
                # “Không, tôi muốn mua sữa rửa mặt” means replace the old
                # combo quote, not cancel checkout and lose the new product.
                items = []
            by_product = {int(item["product_id"]): item for item in items}
            for product in additional_products:
                quantity = _extract_quantity_for_product(text, product, len(additional_products))
                available = max(
                    int(product.stock_quantity or 0) - int(product.reserved_quantity or 0),
                    0,
                )
                existing = by_product.get(product.id)
                requested_quantity = quantity + int(existing.get("quantity") or 0) if existing else quantity
                if existing is None:
                    try:
                        unit_price = Decimal(str(product.price or 0))
                    except (InvalidOperation, TypeError, ValueError):
                        unit_price = Decimal("0")
                    existing = {
                        "product_id": product.id,
                        "product_name": product.name,
                        "quantity": 0,
                        "unit_price": str(unit_price),
                        "available": available,
                    }
                    items.append(existing)
                    by_product[product.id] = existing
                existing["quantity"] = requested_quantity
                existing["available"] = available

            shortages = [item for item in items if int(item.get("quantity") or 1) > int(item.get("available") or 0)]
            if shortages:
                return CollectionFlowResult(
                    session_id=session.id,
                    status=session.status,
                    current_field=session.current_field,
                    prompt=_stock_unavailable_prompt(items),
                )
            _set_quote_items(quote, items)
            session.collected_fields = quote
            session.last_activity_at = _now()
            db.commit()
            return CollectionFlowResult(
                session_id=session.id,
                status=session.status,
                current_field=session.current_field,
                prompt=_format_quote_prompt(items),
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
    otp_pending = False
    if draft_order is not None:
        otp_pending = _create_checkout_otp_challenges(
            db,
            session=session,
            order=draft_order,
        )
        collected = dict(session.collected_fields or {})
        # Keep this explicit state even when a previously verified contact
        # means no new challenge is required.  It lets the next inbound
        # message be an idempotent confirmation instead of falling to RAG.
        collected["awaiting_customer_confirmation"] = not otp_pending
        session.collected_fields = collected
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
        collected = dict(session.collected_fields or {})
        if otp_pending:
            prompt = _checkout_otp_prompt(
                draft_order,
                delivery_pending=bool(collected.get("otp_delivery_pending")),
                delivery_channels=list(collected.get("otp_delivery_channels") or []),
                demo_codes=list(getattr(session, "_otp_demo_codes", []) or []),
            )
        else:
            prompt = (
                f"Mình đã tạo đơn nháp {draft_order.order_number} cho {collected['name']}. "
                f"Phương thức thanh toán: {'COD' if collected['payment_method'] == 'cod' else 'chuyển khoản'}. "
                f"Thông tin liên hệ đã xác thực. Bạn xác nhận chốt đơn {draft_order.order_number} chứ?"
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
    auto_reply_key: str | None = None,
) -> None:
    """Send and persist the next collection prompt off the webhook path."""

    def worker() -> None:
        db = SessionLocal()
        try:
            # These helpers are imported lazily to avoid coupling the model
            # collection service to provider integrations during unit tests.
            from app.services.auto_reply_service import (
                _claim_auto_reply,
                _get_conversation_recipient,
                _mark_auto_reply_failed,
                _save_auto_reply_outbound,
                _send_channel_reply,
            )

            stored_channel, recipient_id = _get_conversation_recipient(
                db,
                conversation_id,
                business_id,
            )
            if auto_reply_key and not _claim_auto_reply(
                db,
                conversation_id=conversation_id,
                channel=stored_channel,
                recipient_id=recipient_id,
                content=result.prompt,
                business_id=business_id,
                auto_reply_key=auto_reply_key,
            ):
                return
            meta_response = _send_channel_reply(
                db=db,
                conversation_id=conversation_id,
                channel=stored_channel,
                recipient_id=recipient_id,
                text=result.prompt,
                business_id=business_id,
            )
            save_kwargs = {
                "db": db,
                "conversation_id": conversation_id,
                "channel": stored_channel,
                "recipient_id": recipient_id,
                "external_message_id": meta_response.get("message_id"),
                "content": result.prompt,
                "meta_response": meta_response,
                "source_document_ids": [],
            }
            if auto_reply_key:
                save_kwargs["auto_reply_key"] = auto_reply_key
            _save_auto_reply_outbound(**save_kwargs)
        except Exception as error:
            if auto_reply_key:
                try:
                    _mark_auto_reply_failed(db, auto_reply_key, error)
                except Exception:
                    pass
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
