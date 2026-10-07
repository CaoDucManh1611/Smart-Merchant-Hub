"""Progressive customer-profile collection for inbound sales conversations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
from threading import Thread
import unicodedata

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.customer import Customer
from app.models.conversation import Conversation
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
    product_display_name,
    resolve_product_mentions,
)
from app.rag.prompt_builder import detect_reply_language
from app.services.notification_service import create_notification
from app.database.tenant_session import tenant_session
from app.tenancy.schema import schema_name_for


REQUIRED_FIELDS = ("name", "phone", "email", "address", "payment_method")
SHOPEE_REQUIRED_FIELDS = ("name", "email", "address", "payment_method")


def _required_fields_for_channel(source_channel: str | None) -> tuple[str, ...]:
    if str(source_channel or "").strip().lower() == "shopee":
        return SHOPEE_REQUIRED_FIELDS
    return REQUIRED_FIELDS


PAYMENT_METHODS = {
    "cod": {"cod", "cash on delivery", "thu tien khi nhan", "thanh toan khi nhan", "nhan hang moi tra"},
    "bank_transfer": {"chuyen khoan", "chuyen khoan ngan hang", "bank transfer", "ck", "qr"},
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
    "hey there",
    "hi",
    "hi there",
    "hello there",
    "xin chao",
    "xin chao ban",
    "xin chao shop",
}
GREETING_REPLY = "Chào bạn! Mình có thể giúp bạn tìm sản phẩm hoặc tư vấn đơn hàng hôm nay nhé."
GREETING_REPLY_EN = "Hi! I can help you find a product or answer questions about an order today."
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
    "con hang",
    "con hang khong",
    "con may chiec",
    "con may cai",
    "con bao nhieu chiec",
    "con bao nhieu cai",
    "du khong",
    "co san khong",
    "in stock",
    "available",
)
GENERIC_PURCHASE_WORDS = {"hang", "do", "san", "pham"}
ENGLISH_QUANTITY_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}
ENGLISH_PRICE_PHRASES = ("how much", "what does", "what is the price", "cost")
ENGLISH_PURCHASE_MARKERS = (
    "i want to buy", "i would like to buy", "i d like to buy", "i wanna buy",
    "i wana buy", "i want to order", "please order", "i ll take", "i will take",
)
BROWSING_PHRASES = (
    "tim hieu",
    "danh sach san pham",
    "danh sach do",
    "danh sach mat hang",
    "liet ke san pham",
    "liet ke mat hang",
    "san pham nao",
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
PRODUCT_MEASURE_UNITS = re.compile(r"\s*(?:ml|l|lit|kg|g|cm|mm)\b")
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
    folded = re.sub(r"[^\w\s]", " ", _fold(str(text or "")))
    folded = " ".join(folded.split())
    if _is_product_detail_request(folded):
        return False
    if _is_purchase_history_question(folded):
        return False
    if any(phrase in folded for phrase in ORDER_CONFIRMATION_PHRASES):
        return True
    if (
        is_price_quote_request(folded)
        or is_stock_query_request(folded)
        or _looks_like_product_discovery(folded)
        or _looks_like_english_product_discovery(folded)
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

    for marker in ENGLISH_PURCHASE_MARKERS:
        marker_position = folded.find(marker + " ")
        if marker_position < 0:
            continue
        tail = folded[marker_position + len(marker):].strip()
        if tail in {"something", "anything", "a product", "some product", "product", "products", "an item", "a thing"}:
            continue
        if tail:
            return True
    if re.search(
        r"\bi want (?:\d{1,4}|" + "|".join(ENGLISH_QUANTITY_WORDS) + r")\s+\w",
        folded,
    ):
        return True
    return False


def is_price_quote_request(text: str | None) -> bool:
    """Detect a quantity/price question, not a confirmed purchase."""
    folded = _fold(str(text or ""))
    return _has_explicit_quantity(folded) and (
        any(phrase in folded for phrase in PRICE_QUERY_PHRASES)
        or bool(re.search(r"\b(?:tong tien|tinh tong|tong cong)\b", folded))
        or any(phrase in folded for phrase in ENGLISH_PRICE_PHRASES)
    )


def is_stock_query_request(text: str | None) -> bool:
    """Detect an availability question, not a confirmed purchase."""
    folded = _fold(str(text or ""))
    return any(phrase in folded for phrase in STOCK_QUERY_PHRASES)


def _has_explicit_quantity(text: str) -> bool:
    """Return whether text contains a quantity, excluding model/SKU numbers.

    Product names often end in a number (``mẫu 01``, ``model 2024``).  The
    old detector treated that number as a requested quantity and started
    checkout for a simple price/stock question.
    """
    for match in QUANTITY_PATTERN.finditer(text):
        if _is_product_measurement(text, match):
            continue
        prefix = text[max(0, match.start() - 16):match.start()]
        if re.search(r"(?:\b(?:mau|model|sku|ma)\s*)$", prefix):
            continue
        return True
    for match in re.finditer(r"\b(?:" + "|".join(ENGLISH_QUANTITY_WORDS) + r")\b", text):
        prefix = text[max(0, match.start() - 16):match.start()]
        if re.search(r"(?:\b(?:mau|model|sku|ma)\s*)$", prefix):
            continue
        suffix = text[match.end():match.end() + 24]
        if re.match(r"\s+(?:units?|items?|pieces?|products?)\b", suffix) or re.search(
            r"\b(?:buy|take|order|want|need)\b", prefix
        ):
            return True
    return False


def _is_product_measurement(text: str, match: re.Match[str]) -> bool:
    """A capacity/size in a product name is not an order quantity."""
    before = text[match.start() - 1:match.start()] if match.start() else ""
    after = text[match.end():match.end() + 12]
    return before in {".", ","} or after.startswith((".", ",")) or bool(PRODUCT_MEASURE_UNITS.match(after))


def _is_checkout_information_question(text: str) -> bool:
    """Keep general questions from being consumed by a pending quote.

    A customer may ask about shipping, return rules, or another product while
    a draft quote is waiting for confirmation.  Those messages are not an
    approval/rejection of the draft and must go back to the normal chatbot.
    """
    folded = _fold(str(text or ""))
    return any(term in folded for term in (
        "giao hang", "van chuyen", "phi ship", "ship", "doi tra", "tra hang",
        "hoan tien", "bao hanh", "chinh sach", "link", "lien ket", "duong dan", "url",
    ))


def _is_product_detail_request(text: str | None) -> bool:
    folded = _fold(str(text or ""))
    if any(term in folded for term in ("don hang", "hoa don", "ma don", "order status", "invoice")):
        return False
    return any(term in folded for term in ("chi tiet", "mo ta san pham", "thong so san pham"))


def _format_vnd(value: object) -> str:
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal("0")
    return f"{amount:,.0f}".replace(",", ".")


def _format_quote_amount(value: object, language: str) -> str:
    amount = _format_vnd(value)
    return amount if language != "en" else amount.replace(".", ",")


def _invoice_confirmation_prompt(order: Order, *, payment_method: str | None = None) -> str:
    """Show a clear invoice before the customer can hand work to staff."""
    items = ", ".join(
        f"{item.product_name_snapshot or item.sku_snapshot or 'Sản phẩm'} × {item.quantity}"
        for item in (order.items or [])
    ) or "Sản phẩm đang chờ cập nhật"
    payment = "COD" if payment_method == "cod" else "chuyển khoản"
    return (
        f"🧾 Hóa đơn tạm tính {order.order_number}\n"
        f"• Sản phẩm: {items}\n"
        f"• Tổng tiền: {_format_vnd(order.total_amount)} đồng\n"
        f"• Thanh toán: {payment}\n"
        "Thông tin liên hệ đã xác thực.\n"
        "Bạn kiểm tra và nhắn “Xác nhận” để chuyển đơn cho nhân viên phụ trách duyệt nhé."
    )


def _extract_quantity(text: str) -> int:
    folded = _fold(text)
    correction = re.search(r"\b(?:doi|sua|thay)(?:\s+tu\s+\d+)?\s+(?:thanh|bang)\s+", folded)
    if correction:
        folded = folded[correction.end():]
    for match in QUANTITY_PATTERN.finditer(folded):
        if _is_product_measurement(folded, match):
            continue
        prefix = folded[max(0, match.start() - 16):match.start()]
        if not re.search(r"(?:\b(?:mau|model|sku|ma)\s*)$", prefix):
            return int(match.group(1))
    for match in re.finditer(r"\b(?:" + "|".join(ENGLISH_QUANTITY_WORDS) + r")\b", folded):
        prefix = folded[max(0, match.start() - 16):match.start()]
        if not re.search(r"(?:\b(?:mau|model|sku|ma)\s*)$", prefix):
            return ENGLISH_QUANTITY_WORDS[match.group(0)]
    return 0


def _is_contextual_quantity_purchase(text: str | None) -> bool:
    folded = " ".join(re.sub(r"[^\w\s]", " ", _fold(str(text or ""))).split())
    quantity = r"(?:\d{1,4}|" + "|".join(ENGLISH_QUANTITY_WORDS) + r")"
    return bool(re.fullmatch(
        r"(?:(?:cho\s+)?(?:toi|minh|em|anh|chi)\s+)?(?:muon\s+)?(?:(?:lay|mua)\s+)?"
        + quantity
        + r"\s+(?:cai|chiec|bo|sp|san\s+pham|items?|units?|pieces?)"
        + r"(?:\s+(?:do|nay|nhe|thoi|please))?",
        folded,
    ))


def _is_quantity_only_update(text: str) -> bool:
    folded = " ".join(re.sub(r"[^\w\s]", " ", _fold(str(text or ""))).split())
    folded = re.sub(
        r"^(?:(?:sua|doi) thanh|actually make (?:that|it)|make (?:that|it)|change (?:it )?to|set (?:it )?to)\s+",
        "",
        folded,
    )
    return bool(re.fullmatch(
        r"(?:(?:toi|minh|ban|i|we|you)\s+)?(?:(?:muon|want|need|mua|buy|lay|get)\s+)*"
        r"(?:\d{1,4}|" + "|".join(ENGLISH_QUANTITY_WORDS) + r")\s*"
        r"(?:cai|bo|sp|san pham|items?|units?|pieces?)?"
        r"(?:\s+(?:do|nay|thoi|nhe|please))?",
        folded,
    ))


def _is_quantity_replacement(text: str) -> bool:
    """A correction changes the quoted quantity; explicit add wording increments it."""
    folded = " ".join(_fold(str(text or "")).split())
    if any(phrase in folded for phrase in ("mua them", "them vao", "add ", "another ")):
        return False
    return any(phrase in folded for phrase in (
        "doi thanh", "doi tu", "sua thanh", "thay bang", "change to", "change it to",
        "make that", "make it", "set it to", "actually make",
    )) or bool(re.search(r"\blay\s+\d+\s+(?:cai|chiec|bo|thoi)\b", folded))


def _is_quantity_decrease(text: str) -> bool:
    return bool(re.search(r"\b(?:bot|giam|tru)\s+\d+\b", _fold(text)))


def _is_underspecified_purchase_request(text: str | None) -> bool:
    folded = " ".join(re.sub(r"[^\w\s]", " ", _fold(str(text or ""))).split())
    if folded in {
        "mua hang", "toi muon mua hang", "muon mua hang", "mua san pham",
        "toi muon mua san pham", "muon mua san pham", "toi muon mua do",
        "i want to buy something", "i want to buy anything", "i want to buy a product",
        "i want to buy some product", "i want to buy products", "i want to buy an item",
        "i want to buy a thing",
    }:
        return True
    has_purchase_verb = bool(re.search(r"\b(?:mua|lay|dat|chot|buy|take|get|order)\b", folded))
    has_quantity = _has_explicit_quantity(folded)
    has_product_hint = bool(re.search(r"\b(?:san pham|hang|mau|model|sku|size|color|colour)\b", folded))
    return has_purchase_verb and has_quantity and not has_product_hint


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
        alias_tokens = [
            token
            for token in normalize_product_text(alias).split()
            if len(token) >= 2 and not token.isdigit()
        ]
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
        item["unit_price"] = str(Decimal(str(product.price or 0)))
        item["product_name"] = product.name
        item["product_name_en"] = product_display_name(product, "en")
        item["available"] = max(
            int(product.stock_quantity or 0) - int(product.reserved_quantity or 0),
            0,
        )


def _format_quote_prompt(items: list[dict], *, language: str = "vi") -> str:
    item_name = lambda item: _quote_product_name(item, language)
    if language == "en":
        if len(items) == 1:
            item = items[0]
            quantity = int(item.get("quantity") or 1)
            total = Decimal(str(item.get("unit_price") or 0)) * quantity
            return (
                f"Would you like {quantity} {item_name(item)}? "
                f"Unit price: ₫{_format_quote_amount(item.get('unit_price'), language)}, "
                f"total: ₫{_format_quote_amount(total, language)} (in stock: {item.get('available', 0)}). "
                "Would you like to place the order?"
            )
        product_text = ", ".join(
            f"{int(item.get('quantity') or 1)} {item_name(item)} "
            f"(₫{_format_quote_amount(item.get('unit_price'), language)} each)"
            for item in items
        )
        total = sum(
            Decimal(str(item.get("unit_price") or 0)) * int(item.get("quantity") or 1)
            for item in items
        )
        stock_text = ", ".join(
            f"{item_name(item)}: {item.get('available', 0)} in stock"
            for item in items
        )
        return f"Your selection: {product_text}. Total: ₫{_format_quote_amount(total, language)} ({stock_text}). Place the order?"

    if len(items) == 1:
        item = items[0]
        total = Decimal(str(item.get("unit_price") or 0)) * int(item.get("quantity") or 1)
        return (
            f"Bạn muốn mua {int(item.get('quantity') or 1)} {item_name(item)}. "
            f"Đơn giá {_format_vnd(item.get('unit_price'))} đồng, tổng cộng {_format_vnd(total)} đồng "
            f"(shop còn {item.get('available', 0)}). Bạn xác nhận đặt hàng chứ?"
        )

    product_parts = [
        f"{int(item.get('quantity') or 1)} {item_name(item)} "
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
        f"{item_name(item)}: còn {item.get('available', 0)}"
        for item in items
    )
    return (
        f"Bạn muốn mua {product_text}. Tổng cộng {_format_vnd(total)} đồng "
        f"({stock_text}). Bạn xác nhận đặt hàng chứ?"
    )


def _quote_product_name(item: dict, language: str) -> str:
    return (
        item.get("product_name_en") or item.get("product_name") or "Product"
        if language == "en"
        else item.get("product_name") or "Sản phẩm"
    )


_ORDER_FORM_LABELS = {
    "ten nguoi nhan": "name",
    "ho ten": "name",
    "ho va ten": "name",
    "ten": "name",
    "recipient name": "name",
    "name": "name",
    "so dien thoai": "phone",
    "dien thoai": "phone",
    "sdt": "phone",
    "so dt": "phone",
    "phone": "phone",
    "phone number": "phone",
    "mobile": "phone",
    "email": "email",
    "thu dien tu": "email",
    "dia chi nhan hang": "address",
    "dia chi giao hang": "address",
    "dia chi": "address",
    "shipping address": "address",
    "delivery address": "address",
    "address": "address",
    "phuong thuc thanh toan": "payment_method",
    "hinh thuc thanh toan": "payment_method",
    "thanh toan": "payment_method",
    "payment method": "payment_method",
    "payment": "payment_method",
}


def _order_form_prompt(required_fields: list[str] | tuple[str, ...], language: str) -> str:
    labels = {
        "name": "Recipient name" if language == "en" else "Tên người nhận",
        "phone": "Phone number" if language == "en" else "Số điện thoại",
        "email": "Email",
        "address": "Delivery address" if language == "en" else "Địa chỉ nhận hàng",
        "payment_method": "Payment (COD/bank transfer)" if language == "en" else "Thanh toán (COD/chuyển khoản)",
    }
    if language == "en":
        intro = (
            "Please complete every field below. If you send the details in a few messages, "
            "I will keep them together instead of asking for each field again:\n"
        )
    else:
        intro = (
            "Để lên đơn, bạn điền đầy đủ các mục dưới đây nhé. Nếu gửi thành vài tin, "
            "mình sẽ tự ghi nhận thay vì hỏi lại từng mục:\n"
        )
    return intro + "\n".join(f"{labels[field]}:" for field in required_fields if field in labels)


def _split_order_form_line(line: str) -> tuple[str | None, str]:
    for label, field in sorted(_ORDER_FORM_LABELS.items(), key=lambda item: len(item[0]), reverse=True):
        for boundary in range(1, len(line) + 1):
            if _fold(line[:boundary]).strip() != label:
                continue
            remainder = line[boundary:]
            if remainder and not (remainder[0].isspace() or remainder[0] in ":：=—-"):
                continue
            return field, remainder.lstrip(" \t:：=—-").strip()
    return None, ""


def _fold_with_positions(value: str) -> tuple[str, list[int]]:
    """Fold accents while retaining offsets into the original message."""
    folded_chars: list[str] = []
    original_positions: list[int] = []
    for index, char in enumerate(value):
        normalized = unicodedata.normalize("NFKD", char.casefold()).replace("đ", "d")
        for item in normalized:
            if unicodedata.combining(item):
                continue
            folded_chars.append(item)
            original_positions.append(index)
    return "".join(folded_chars), original_positions


def _split_order_form_line_parts(line: str) -> list[tuple[str, str]]:
    """Read multiple labeled fields from one message line, preserving addresses."""
    folded, positions = _fold_with_positions(line)
    candidates: list[tuple[int, int, str, str]] = []
    for label, field in _ORDER_FORM_LABELS.items():
        pattern = re.compile(rf"(?<![a-z0-9]){re.escape(label)}(?![a-z0-9])")
        for match in pattern.finditer(folded):
            start, end = match.span()
            original_start = positions[start]
            original_end = positions[end - 1] + 1
            candidates.append((original_start, original_end, label, field))

    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    labels: list[tuple[int, int, str]] = []
    for start, end, _label, field in candidates:
        if labels and start < labels[-1][1]:
            continue
        if not labels:
            # A line may begin with a small conversational lead-in, but don't
            # treat an incidental word like "email" inside an address as a
            # form label unless it follows a recognized field.
            prefix = line[:start].strip(" \t,;|:：=—-")
            if prefix and _fold(prefix) not in {"minh", "toi", "ten", "ho ten"}:
                continue
        labels.append((start, end, field))

    parts: list[tuple[str, str]] = []
    for index, (_start, end, field) in enumerate(labels):
        next_start = labels[index + 1][0] if index + 1 < len(labels) else len(line)
        raw_value = line[end:next_start].strip(" \t,;|:：=—-")
        parts.append((field, raw_value))
    return parts


def _parse_order_form_details(
    text: str,
    required_fields: list[str] | tuple[str, ...],
    fragments: list[str] | None = None,
    fallback_field: str | None = None,
) -> tuple[dict[str, str], bool, set[str]]:
    required = set(required_fields)
    values: dict[str, str] = {}
    found_form = False
    invalid_fields: set[str] = set()
    source = "\n".join(fragments) if fragments else str(text or "")
    lines = [line.strip() for line in re.split(r"[\r\n;|]+", source) if line.strip()]
    unlabelled: list[str] = []
    for line in lines:
        labeled_parts = _split_order_form_line_parts(line)
        if not labeled_parts:
            unlabelled.append(line)
            continue
        for field, raw_value in labeled_parts:
            found_form = True
            if field not in required:
                continue
            if field == "payment_method" and ":" in raw_value:
                # Drop example text from labels such as "Payment (COD/bank
                # transfer): ..." before looking for the selected method.
                raw_value = raw_value.rsplit(":", 1)[-1]
            value = _extract_value(field, raw_value)
            if value:
                values[field] = value
                invalid_fields.discard(field)
            else:
                invalid_fields.add(field)

    # The conversation-turn worker already groups rapid-fire chat fragments.
    # Customers may therefore answer in the same order as the displayed form
    # without repeating labels. Accept a complete positional batch only when
    # every line maps cleanly; partial turns are handled below and persisted.
    if not found_form and len(lines) == len(required_fields):
        positional = {
            field: value
            for field, raw_value in zip(required_fields, lines)
            if (value := _extract_value(field, raw_value))
        }
        if len(positional) == len(required_fields):
            return positional, True, set()

    fallback_used = False
    for line in unlabelled:
        inferred_field = next(
            (
                field for field in ("email", "phone", "payment_method")
                if (value := _extract_value(field, line))
            ),
            None,
        )
        if inferred_field is not None:
            found_form = True
            if inferred_field in required:
                values[inferred_field] = _extract_value(inferred_field, line) or ""
            continue
        # When a customer replies with a bare value (for example just their
        # name) after seeing the form, assign one such fragment to the next
        # missing field. This supports short chat messages without asking the
        # same full form again after every batch.
        if not fallback_used and required_fields:
            field = fallback_field if fallback_field in required else required_fields[0]
            value = _extract_value(field, line)
            if value:
                found_form = True
                values[field] = value
                fallback_used = True

    return values, found_form, invalid_fields


def _parse_order_form(
    text: str,
    required_fields: list[str] | tuple[str, ...],
    fragments: list[str] | None = None,
) -> tuple[dict[str, str], bool]:
    values, found_form, _invalid_fields = _parse_order_form_details(
        text,
        required_fields,
        fragments,
    )
    return values, found_form


def _stock_unavailable_prompt(items: list[dict], *, language: str = "vi") -> str:
    if language == "en":
        shortages = [
            f"{_quote_product_name(item, language)}: only {item.get('available', 0)} available "
            f"(requested {int(item.get('quantity') or 1)})"
            for item in items
            if int(item.get("quantity") or 1) > int(item.get("available") or 0)
        ]
        return "Insufficient stock: " + "; ".join(shortages) + ". Would you like to reduce the quantity or choose another product?"
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
            prompt=(
                "I couldn't match that item to the shop catalog. Please send its exact product name or SKU."
                if detect_reply_language(text) == "en"
                else "Mình chưa tìm thấy sản phẩm bạn vừa hỏi. Bạn cho mình tên hoặc mã sản phẩm chính xác nhé."
            ),
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
            "product_name_en": product_display_name(product, "en"),
            "quantity": quantity,
            "unit_price": str(product.price),
            "available": available,
        })

    if any(int(item["quantity"]) > int(item["available"]) for item in items):
        return CollectionFlowResult(
            session_id=0,
            status="stock_unavailable",
            current_field=None,
            prompt=_stock_unavailable_prompt(items, language=detect_reply_language(text)),
            started=True,
        )

    folded = " ".join(_fold(text).split())
    quote_only = any(phrase in folded for phrase in (
        "chi hoi gia", "chua dat hang", "chua xac nhan dat hang",
        "khong tao don", "khong dat hang", "chi tinh tong", "van chi hoi gia",
        "just asking the price", "just asking for the price", "not placing an order",
    ))
    if quote_only:
        total = sum(Decimal(str(item["unit_price"])) * int(item["quantity"]) for item in items)
        language = detect_reply_language(text)
        names = ", ".join(f"{item['quantity']} {_quote_product_name(item, language)}" for item in items)
        prompt = (
            f"{names}: ₫{_format_quote_amount(total, language)} in total. No order has been placed."
            if language == "en" else
            f"{names}: tổng cộng {_format_vnd(total)} đồng. Mình chưa tạo đơn hàng nhé."
        )
        return CollectionFlowResult(session_id=0, status="catalog_answer", current_field=None, prompt=prompt)

    collected = {"reply_language": detect_reply_language(text)}
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
        prompt=_format_quote_prompt(items, language=detect_reply_language(text)),
        started=True,
    )


def _is_order_approval(text: str | None) -> bool:
    folded = " ".join(re.sub(r"[^\w\s]", " ", _fold(str(text or ""))).split())
    return folded in {"yes", "yes please", "confirm", "confirmed", "go ahead"} or any(
        phrase in folded for phrase in ORDER_APPROVAL_PHRASES
    ) or folded.startswith(("i ll take ", "i will take "))


def _is_order_rejection(text: str | None) -> bool:
    folded = " ".join(re.sub(r"[^\w\s]", " ", _fold(str(text or ""))).split())
    return folded in {
        "khong", "khong nhe", "khong cam on", "khong can", "thoi khong",
        "khong mua nua", "khong dat nua", "khong lay nua", "huy", "huy don",
        "huy yeu cau", "de sau", "chua mua", "no", "no thanks", "not now",
        "i changed my mind", "cancel", "cancel order",
    }


def _is_product_switch_request(text: str | None) -> bool:
    """Detect a rejection that immediately names the product to keep."""
    folded = " ".join(re.sub(r"[^\w\s]", " ", _fold(str(text or ""))).split())
    if any(term in folded for term in ("mua them", "them vao", "add ", "also ", "another ")):
        return False
    return (
        any(phrase in folded for phrase in (
            "muon mua", "chi mua", "doi sang", "thay bang", "y toi la", "khong phai",
            "i mean", "i meant", "instead",
        ))
        or folded.startswith(("no ", "not that ", "actually ", "khong "))
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
    if _is_product_detail_request(folded):
        return True
    # A reference to a previously discussed item is not a request to list
    # every product merely because it contains "mau ... khong".
    if re.search(r"\b(?:mau|san pham)\s+(?:do|nay|vua hoi)\b", folded):
        return False
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
    if _looks_like_english_product_discovery(folded):
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
    return bool(re.search(r"\b(?:mua|dat|lay|chot|buy|take|order)\b", folded))


def _looks_like_product_discovery(folded: str) -> bool:
    if any(phrase in folded for phrase in BROWSING_PHRASES):
        return True
    return bool(
        re.search(r"\b(?:co|con|xem|tim|goi y|tu van|muon mua)\b.*\b(?:san pham|hang|mau)\b", folded)
        or re.search(r"\b(?:san pham|hang|mau)\b.*\b(?:gi|nao|khong)\b", folded)
        or "mua hang" in folded
    )


def _looks_like_english_product_discovery(folded: str) -> bool:
    return bool(
        re.search(
            r"\b(?:what|which) products?\b|\bwhat do you (?:have|sell)\b|"
            r"\b(?:show|list|browse) (?:me )?(?:your )?(?:the )?(?:available )?(?:products?|items?|catalog(?:ue)?)\b|"
            r"\b(?:i want|i would like|i'd like) to (?:see|browse|buy) (?:a |some )?products?\b|"
            r"\bproduct catalog(?:ue)?\b",
            folded,
        )
    )


def _is_purchase_history_question(folded: str) -> bool:
    return bool(
        re.search(r"\bwhat (?:did i|was i) (?:just )?(?:buy|order|purchase)\b", folded)
        or (
            "mua gi" in folded
            and any(term in folded for term in ("vua", "nay", "luc nay", "hoi"))
        )
    )


def _recent_quote_history_reply(
    db: Session,
    *,
    business_id: int,
    customer_id: int,
    conversation_id: int | None,
    text: str,
) -> CollectionFlowResult | None:
    folded = _fold(str(text or ""))
    if not _is_purchase_history_question(folded) or conversation_id is None:
        return None

    session = db.query(CustomerCollectionSession).filter(
        CustomerCollectionSession.business_id == business_id,
        CustomerCollectionSession.customer_id == customer_id,
        CustomerCollectionSession.conversation_id == conversation_id,
        CustomerCollectionSession.purpose == "order_confirmation",
        CustomerCollectionSession.status.in_(("pending", "abandoned")),
        CustomerCollectionSession.last_activity_at >= _now() - timedelta(hours=24),
    ).order_by(CustomerCollectionSession.id.desc()).first()
    if session is None:
        return None

    items = _quote_items(dict(session.collected_fields or {}))
    if not items:
        return None
    summary = ", ".join(
        f"{int(item.get('quantity') or 1)} {item.get('product_name') or 'Sản phẩm'}"
        for item in items
    )
    collected = dict(session.collected_fields or {})
    total = _format_vnd(collected.get("total_amount"))
    was_cancelled = collected.get("confirmation_status") in {"declined", "cancelled"}
    if detect_reply_language(text) == "en":
        if session.status == "abandoned":
            outcome = "You cancelled that request, so there is no confirmed order." if was_cancelled else (
                "That request was not confirmed, so no order was placed."
            )
            prompt = f"You asked about ordering {summary} (total: ₫{total}). {outcome}"
        else:
            prompt = (
                f"You were reviewing a quote for {summary} (total: ₫{total}). "
                "It has not been confirmed, so no order has been placed yet."
            )
    elif session.status == "abandoned":
        outcome = "Bạn đã hủy yêu cầu này nên chưa có đơn hàng được xác nhận." if was_cancelled else (
            "Yêu cầu này chưa được xác nhận nên chưa có đơn hàng được tạo."
        )
        prompt = f"Trước đó bạn hỏi đặt {summary}, tổng cộng {total} đồng. {outcome}"
    else:
        prompt = (
            f"Bạn đang xem báo giá {summary}, tổng cộng {total} đồng. "
            "Bạn chưa xác nhận nên đơn hàng chưa được tạo."
        )
    return CollectionFlowResult(
        session_id=session.id,
        status="history_answer",
        current_field=None,
        prompt=prompt,
    )


def greeting_reply(text: str | None) -> str:
    return GREETING_REPLY_EN if detect_reply_language(str(text or "")) == "en" else GREETING_REPLY


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


def _ensure_channel_fields(session: CustomerCollectionSession) -> bool:
    """Upgrade active sessions created while checkout used one generic contact field."""
    fields = list(session.required_fields or [])
    is_shopee = str(session.source_channel or "").strip().lower() == "shopee"
    if "contact" not in fields and not (is_shopee and "phone" in fields):
        return False

    collected = dict(session.collected_fields or {})
    # Older builds retained the chosen value under its typed key as well.
    collected.pop("contact", None)
    fields = list(_required_fields_for_channel(session.source_channel))
    session.required_fields = fields
    session.collected_fields = collected

    current_field = session.current_field
    missing = next((field for field in fields if not collected.get(field)), None)
    if current_field not in fields or collected.get(current_field):
        current_field = missing
    elif missing is not None and fields.index(missing) < fields.index(current_field):
        current_field = missing
    if current_field != session.current_field:
        session.current_field = current_field
        session.status = "partial"
    return True


def _extract_value(field: str, text: str) -> str | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    folded = _fold(raw)
    if field == "name":
        value = raw
        for prefix in (
            "tên người nhận", "họ và tên", "họ tên", "tên tôi là", "mình là", "tôi là", "tên", "name",
        ):
            for boundary in range(1, len(raw) + 1):
                if _fold(raw[:boundary]).strip() != _fold(prefix):
                    continue
                remainder = raw[boundary:]
                if remainder and not (remainder[0].isspace() or remainder[0] in ":：=—-,"):
                    continue
                value = remainder.lstrip(" \t:：=—-,").strip()
                value = re.sub(r"^(?:là|is)\s+", "", value, flags=re.IGNORECASE).strip()
                break
            if value != raw:
                break
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
        if collected.get("phone"):
            challenge_channels = (("phone", "sms"),)
        elif collected.get("email"):
            # Shopee checkout intentionally collects email only.  Queueing the
            # unsupported delivery keeps verification pending instead of
            # silently treating the absence of an SMS destination as success.
            challenge_channels = (("email", "email"),)
        else:
            challenge_channels = ()
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
            prompt=_invoice_confirmation_prompt(order, payment_method=collected.get("payment_method")),
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
        prompt=_invoice_confirmation_prompt(order, payment_method=collected.get("payment_method")),
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
            "invoice_confirmation_status": "awaiting_customer",
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
    # Do not notify staff while the draft is being prepared. The customer
    # must review the invoice first; staff receive a targeted notification
    # only after explicit customer approval below.
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
    form_fragments: list[str] | None = None,
) -> CollectionFlowResult | None:
    """Start or advance a collection session from one coalesced chat turn."""
    customer = db.query(Customer).filter(
        Customer.id == customer_id,
        Customer.business_id == business_id,
        Customer.status != "merged",
    ).first()
    if customer is None:
        return None

    # Stock questions belong to the assistant's factual catalogue route. In
    # particular, do not let "còn hàng không?" decline an open quote or turn
    # a product model number (for example 1.8 lít) into a checkout quantity.
    folded_question = _fold(text)
    if is_stock_query_request(text) or (
        not is_price_quote_request(text)
        and (re.search(r"\bgia\b(?!\s+dung\b)", folded_question) or any(phrase in folded_question for phrase in ENGLISH_PRICE_PHRASES))
    ):
        return None

    history_reply = _recent_quote_history_reply(
        db,
        business_id=business_id,
        customer_id=customer_id,
        conversation_id=conversation_id,
        text=text,
    )
    if history_reply is not None:
        return history_reply

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
        if is_price_quote_request(text):
            # A numeric suffix in a product name (for example ``mẫu 01``) is
            # not a purchase quantity.  Only start checkout when a real
            # product mention resolves; otherwise leave the message for the
            # informational bot router to clarify it.
            quoted_products = _find_requested_products(
                db,
                business_id=business_id,
                text=text,
                conversation_id=conversation_id if _is_quantity_replacement(text) else None,
                allow_history=_is_quantity_replacement(text),
            )
            if quoted_products:
                return _start_product_quote(
                    db,
                    business_id=business_id,
                    customer_id=customer_id,
                    conversation_id=conversation_id,
                    source_channel=source_channel,
                    text=text,
                )
            return None
        if _is_product_detail_request(text):
            return None
        if _is_contextual_quantity_purchase(text):
            products = _find_requested_products(
                db,
                business_id=business_id,
                text=text,
                conversation_id=conversation_id,
            )
            if products:
                return _start_product_quote(
                    db,
                    business_id=business_id,
                    customer_id=customer_id,
                    conversation_id=conversation_id,
                    source_channel=source_channel,
                    text=text,
                )
            return CollectionFlowResult(
                session_id=0,
                status="product_clarification",
                current_field=None,
                prompt="Bạn muốn lấy sản phẩm nào ạ? Gửi mình tên hoặc mã sản phẩm để kiểm tra nhé.",
                started=True,
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
        if _is_underspecified_purchase_request(text):
            # The shared assistant can show the live catalogue or ask a
            # context-aware question without opening a checkout session.
            return None
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
            required_fields=list(_required_fields_for_channel(source_channel)),
            collected_fields={"reply_language": detect_reply_language(text)},
            current_field=_required_fields_for_channel(source_channel)[0],
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
            prompt=_order_form_prompt(
                session.required_fields,
                detect_reply_language(text),
            ),
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

        # Do not interpret a shipping/policy question as a rejection of the
        # pending quote.  The previous behavior cancelled the order when the
        # message contained the word "không" (for example, "giao hàng không?")
        # and then blocked all following chatbot replies.
        additional_products = _find_requested_products(
            db,
            business_id=business_id,
            text=text,
            conversation_id=conversation_id,
            allow_history=False,
        )
        informational_price_or_stock = (
            ("gia" in _fold(text) or "ton kho" in _fold(text) or "con hang" in _fold(text))
            and not _has_specific_purchase_signal(text)
        )
        if _is_checkout_information_question(text) or is_browsing_request(text) or (
            informational_price_or_stock and not additional_products
        ):
            session.status = "abandoned"
            session.current_field = None
            session.collected_fields = {**collected_state, "awaiting_customer_confirmation": False}
            session.last_activity_at = _now()
            _cancel_checkout_reminder(
                db,
                business_id=business_id,
                conversation_id=conversation_id,
                session_id=session.id,
            )
            db.commit()
            return None

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
        try:
            transition_sales_order(
                db,
                order_id=order.id,
                to_status="pending_confirmation",
                actor_id=None,
                business_id=business_id,
            )
        except SalesOrderOperationError:
            return CollectionFlowResult(
                session_id=session.id,
                status=session.status,
                current_field=None,
                prompt="Đơn này vừa được cập nhật. Nhân viên sẽ kiểm tra và phản hồi cho bạn nhé.",
                draft_order_id=order.id,
            )
        metadata = dict(order.metadata_ or {})
        metadata["customer_confirmed"] = True
        metadata["customer_confirmed_at"] = _now().isoformat()
        metadata["invoice_confirmation_status"] = "customer_confirmed"
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
        conversation = db.query(Conversation).filter(
            Conversation.id == conversation_id,
            Conversation.business_id == business_id,
        ).first() if conversation_id is not None else None
        # Persist the assignment even when the staff member is offline; the
        # inbox will show it on the next session and realtime delivery remains
        # an additive concern.
        notification_user_id = conversation.assigned_user_id if conversation is not None else None
        create_notification(
            db,
            business_id=business_id,
            user_id=notification_user_id,
            kind="customer_order_confirmation",
            title="Khách đã xác nhận hóa đơn",
            body=f"{order.order_number}: khách đã xác nhận hóa đơn. Vui lòng kiểm tra và xác nhận đơn bán.",
            metadata={"order_id": order.id, "conversation_id": conversation_id, "customer_id": customer_id},
        )
        db.commit()
        return CollectionFlowResult(
            session_id=session.id,
            status=session.status,
            current_field=None,
            prompt=f"Mình đã ghi nhận xác nhận hóa đơn {order.order_number}. Đơn đang chờ nhân viên phụ trách xác nhận và sẽ báo lại cho bạn nhé.",
            completed=True,
            draft_order_id=order.id,
        )

    if is_price_quote_request(text):
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
        reply_language = quote.get("reply_language") or detect_reply_language(text)
        if is_browsing_request(text) or _is_checkout_information_question(text):
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
        is_quantity_replacement = _is_quantity_replacement(text)
        is_quantity_decrease = _is_quantity_decrease(text)
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
                prompt=(
                    "I cancelled that product request. Let me know if you'd like to try again."
                    if reply_language == "en"
                    else "Mình đã hủy yêu cầu đặt sản phẩm này. Khi cần mua lại cứ nhắn mình nhé."
                ),
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
                requested_quantity = (
                    quantity if existing and is_quantity_replacement
                    else int(existing.get("quantity") or 0) - quantity if existing and is_quantity_decrease
                    else quantity + int(existing.get("quantity") or 0) if existing
                    else quantity
                )
                if requested_quantity < 1:
                    return CollectionFlowResult(
                        session_id=session.id, status=session.status, current_field=session.current_field,
                        prompt="Số lượng cần còn ít nhất 1. Nếu bạn muốn hủy, hãy nhắn hủy đơn giúp mình nhé.",
                    )
                if existing is None:
                    try:
                        unit_price = Decimal(str(product.price or 0))
                    except (InvalidOperation, TypeError, ValueError):
                        unit_price = Decimal("0")
                    existing = {
                        "product_id": product.id,
                        "product_name": product.name,
                        "product_name_en": product_display_name(product, "en"),
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
                    prompt=_stock_unavailable_prompt(items, language=reply_language),
                )
            _set_quote_items(quote, items)
            session.collected_fields = quote
            session.last_activity_at = _now()
            db.commit()
            return CollectionFlowResult(
                session_id=session.id,
                status=session.status,
                current_field=session.current_field,
                prompt=_format_quote_prompt(items, language=reply_language),
            )

        if _is_quantity_only_update(text) or is_quantity_replacement or is_quantity_decrease or bool(re.search(r"\bthem\s+\d+\s+nua\b", _fold(text))):
            if len(items) != 1:
                return CollectionFlowResult(
                    session_id=session.id,
                    status=session.status,
                    current_field=session.current_field,
                    prompt=(
                        "This quote has multiple products. Which item's quantity would you like to change?"
                        if reply_language == "en"
                        else "Đơn có nhiều sản phẩm. Bạn muốn đổi số lượng của sản phẩm nào?"
                    ),
                )
            quantity = _extract_quantity(text)
            updated_quantity = (
                int(items[0]["quantity"]) - quantity if is_quantity_decrease
                else int(items[0]["quantity"]) + quantity if re.search(r"\bthem\s+\d+\s+nua\b", _fold(text))
                else quantity
            )
            if updated_quantity < 1:
                return CollectionFlowResult(
                    session_id=session.id, status=session.status, current_field=session.current_field,
                    prompt="Số lượng cần còn ít nhất 1. Nếu bạn muốn hủy, hãy nhắn hủy đơn giúp mình nhé.",
                )
            items[0]["quantity"] = updated_quantity
            _refresh_quote_stock(db, business_id, items)
            _set_quote_items(quote, items)
            session.collected_fields = quote
            session.last_activity_at = _now()
            db.commit()
            if int(items[0]["quantity"]) > int(items[0].get("available") or 0):
                prompt = _stock_unavailable_prompt(items, language=reply_language)
            else:
                prompt = _format_quote_prompt(items, language=reply_language)
            return CollectionFlowResult(
                session_id=session.id,
                status=session.status,
                current_field=session.current_field,
                prompt=prompt,
            )

        if not _is_order_approval(text):
            return CollectionFlowResult(
                session_id=session.id,
                status=session.status,
                current_field=session.current_field,
                prompt=_format_quote_prompt(items, language=reply_language),
            )
        session.purpose = "order"
        required_fields = _required_fields_for_channel(session.source_channel or source_channel)
        session.required_fields = list(required_fields)
        session.current_field = required_fields[0]
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
            prompt=_order_form_prompt(
                session.required_fields,
                reply_language,
            ),
        )

    # Quantity edits after accepting a quote invalidate that acceptance.
    # Return to the quote rather than treating "đổi thành 3" as a name/address.
    if session.purpose == "order" and session.status == "partial" and (
        _is_quantity_replacement(text) or _is_quantity_decrease(text)
        or re.search(r"\bthem\s+\d+\s+nua\b", _fold(text))
    ):
        session.purpose = "order_confirmation"
        session.status = "pending"
        session.current_field = None
        db.commit()
        return advance_customer_collection(
            db, business_id=business_id, customer_id=customer_id,
            conversation_id=conversation_id, source_channel=source_channel, text=text,
            form_fragments=form_fragments,
        )

    if _ensure_channel_fields(session):
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
    collected = dict(session.collected_fields or {})
    values, form_submitted, invalid_fields = _parse_order_form_details(
        text,
        session.required_fields,
        form_fragments,
        fallback_field=field,
    )
    if not form_submitted:
        # Let ordinary questions reach RAG while leaving this checkout open.
        return None

    # Repair partial checkouts saved by older builds that treated a combined
    # "name, phone" line as one name value. This only runs when the customer
    # sends another recognizable form value; it never creates an order by
    # itself or replays outbound messages.
    legacy_name_repaired = False
    saved_name = str(collected.get("name") or "").strip()
    if saved_name:
        recovered, _, _ = _parse_order_form_details(
            f"Tên người nhận: {saved_name}",
            session.required_fields,
        )
        recovered_name = recovered.get("name")
        if recovered_name and recovered_name != saved_name:
            collected["name"] = recovered_name
            legacy_name_repaired = True
        for recovered_field, recovered_value in recovered.items():
            if recovered_value and not collected.get(recovered_field):
                values.setdefault(recovered_field, recovered_value)

    for collected_field, value in values.items():
        collected[collected_field] = value
        if collected_field == "name" and not customer.name:
            customer.name = value
        elif collected_field == "phone":
            _store_contact(db, business_id=business_id, customer_id=customer_id, kind="phone", value=value)
            if not customer.phone:
                customer.phone = value
        elif collected_field == "email":
            _store_contact(db, business_id=business_id, customer_id=customer_id, kind="email", value=value)
            if not customer.email:
                customer.email = value
        elif collected_field == "address":
            _store_address(db, business_id=business_id, customer_id=customer_id, value=value)
            if not customer.address:
                customer.address = value
    if legacy_name_repaired:
        customer.name = collected["name"]
    session.collected_fields = collected
    session.last_activity_at = _now()

    next_field = next((item for item in session.required_fields if not collected.get(item)), None)
    if next_field is not None:
        session.current_field = next_field
        session.status = "partial"
        db.commit()
        invalid_missing = [item for item in session.required_fields if item in invalid_fields and not collected.get(item)]
        if invalid_missing:
            labels = {
                "name": "tên người nhận",
                "phone": "số điện thoại",
                "email": "email",
                "address": "địa chỉ nhận hàng",
                "payment_method": "phương thức thanh toán",
            }
            invalid_labels = ", ".join(labels.get(item, item) for item in invalid_missing)
            language = collected.get("reply_language") or detect_reply_language(text)
            prompt = (
                f"I couldn't read: {invalid_labels}. Please correct those fields in the form:\n"
                if language == "en"
                else f"Mình chưa đọc được {invalid_labels}. Bạn kiểm tra lại các mục đó theo form này nhé:\n"
            ) + _order_form_prompt(session.required_fields, language)
        else:
            # Keep valid fragments across batched turns without sending the
            # full form again after every partial customer message.
            prompt = ""
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
            prompt = _invoice_confirmation_prompt(
                draft_order,
                payment_method=collected.get("payment_method"),
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
        # The webhook request may have already returned, so recreate the
        # tenant context from the trusted business id before touching CRM
        # conversations or channels.  Never reopen the legacy shared session.
        with tenant_session(schema_name_for(business_id)) as db:
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
                    db, conversation_id, business_id
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

    Thread(
        target=worker,
        name="customer-collection-prompt",
        daemon=True,
    ).start()
