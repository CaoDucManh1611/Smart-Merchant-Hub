"""
Auto Reply Service – Tự động trả lời tin nhắn từ RAG knowledge base khi có tin nhắn inbound.
"""

import json
import logging
import re
import unicodedata
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from time import perf_counter
from threading import Lock, Thread

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database.platform_session import PlatformSessionLocal
from app.core.config import settings
from app.database.tenant_session import tenant_session
from app.tenancy.schema import schema_name_for
from app.models.business_setting import BusinessSetting
from app.models.chatbot import ChatbotConfig
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.sales import Product

from app.rag.retriever import retrieve
from app.rag.prompt_builder import build_prompt
from app.rag.llm_caller import call_llm
from app.rag.run_logger import RagRunLog, query_metadata
from app.rag.topics import infer_query_topic
from app.services.facebook_service import send_facebook_message
from app.services.instagram_service import send_instagram_message
from app.services.telegram_service import send_telegram_message
from app.services.zalo_service import send_zalo_message
from app.services.customer_collection_flow import is_browsing_request
from app.services.chatbot_agent import build_agent_memory, is_business_open
from app.services.customer_order_service import customer_order_reply
from app.services.product_resolver import normalize_product_text, product_aliases, resolve_product
from app.services.audit_service import record_audit
from app.services.notification_service import create_notification
from app.services.quota_service import QuotaExceededError, estimate_ai_cost, record_quota_usage
from app.services.realtime import schedule_broadcast
from app.services.realtime import manager
from app.services.chatbot_bandit_service import (
    ChatbotBanditChoice,
    response_style_instruction,
    select_chatbot_reply_choice,
)

logger = logging.getLogger(__name__)

AUTO_REPLY_SETTING_KEY = "rag_auto_reply_enabled"
NO_PRODUCT_CATALOG_REPLY = (
    "Hiện shop chưa cập nhật danh sách sản phẩm. "
    "Bạn cho mình biết nhu cầu, nhân viên sẽ hỗ trợ ngay nhé."
)
OUT_OF_HOURS_REPLY = (
    "Shop hiện đang ngoài giờ hỗ trợ. Mình đã ghi nhận tin nhắn và nhân viên sẽ phản hồi "
    "vào khung giờ làm việc gần nhất nhé."
)

# These replies are deliberately deterministic.  A product catalogue chunk is
# often the largest document in a shop, so semantic retrieval used to make the
# bot answer unrelated questions with the whole catalogue (for example,
# returning product names for a delivery-policy question).  The router below
# handles factual product and policy questions before RAG can mix contexts.
PRODUCT_NOT_FOUND_REPLY = (
    "Mình chưa tìm thấy sản phẩm hoặc mã sản phẩm này trong danh sách của shop. "
    "Bạn kiểm tra lại tên hoặc mã sản phẩm giúp mình nhé."
)
PRODUCT_NOT_FOUND_WITH_HINT = (
    "Mình chưa tìm thấy \"{hint}\" trong danh sách sản phẩm của shop. "
    "Bạn kiểm tra lại tên hoặc mã sản phẩm giúp mình nhé."
)
AMBIGUOUS_PRICE_REPLY = (
    "Bạn muốn hỏi giá sản phẩm nào? Bạn gửi mình tên hoặc mã sản phẩm, "
    "mình sẽ kiểm tra giá và tồn kho chính xác nhé."
)
AMBIGUOUS_STOCK_REPLY = (
    "Bạn muốn kiểm tra tồn kho sản phẩm nào? Bạn gửi mình tên hoặc mã sản phẩm nhé."
)
NO_DELIVERY_POLICY_REPLY = (
    "Mình chưa có thông tin giao hàng cụ thể của shop trong hệ thống. "
    "Bạn cho mình xin khu vực nhận hàng, nhân viên sẽ kiểm tra phí và thời gian giao giúp bạn nhé."
)
NO_RETURN_POLICY_REPLY = (
    "Mình chưa có thông tin chính sách đổi trả của shop trong hệ thống. "
    "Mình đã ghi nhận câu hỏi, nhân viên sẽ tư vấn chính xác cho bạn nhé."
)
NO_RECOMMENDATION_REPLY = (
    "Mình chưa tìm thấy thông tin sản phẩm phù hợp với nhu cầu này trong danh sách của shop. "
    "Bạn cho mình biết thêm nhu cầu, nhân viên sẽ tư vấn ngay nhé."
)

_STOCK_TERMS = (
    "ton kho", "ton", "con hang", "con khong", "co san khong", "du khong",
    "het hang", "so luong", "bao nhieu cai", "bao nhieu san pham",
)
_PRICE_TERMS = (
    "gia", "bao nhieu tien", "thanh tien", "tong tien", "tong bao nhieu", "tinh tien",
    "het bao nhieu", "don gia",
)
_DELIVERY_TERMS = (
    "giao hang", "van chuyen", "phi ship", "cuoc ship", "ship", "nhan hang",
    "thoi gian giao", "khu vuc giao", "giao den",
)
_RETURN_TERMS = (
    "doi tra", "doi hang", "tra hang", "hoan tien", "bao hanh", "chinh sach doi",
)
_RECOMMENDATION_TERMS = (
    "da nhay cam", "phu hop", "goi y", "tu van", "nen dung", "danh cho",
)
_PRODUCT_HINT_STOP_WORDS = {
    "shop", "co", "con", "khong", "cho", "minh", "toi", "ban", "san", "pham",
    "hang", "mau", "nao", "gi", "nhe", "voi", "la", "cua", "gia", "bao",
    "nhieu", "tien", "tong", "thanh", "het", "ton", "kho", "so", "luong", "cai", "hien", "tai",
    "luc", "nay", "hoi", "muon", "xem", "tim", "mua", "duoc", "khong",
}
_NON_PRODUCT_HINT_WORDS = set(_DELIVERY_TERMS + _RETURN_TERMS + (
    "chinh sach", "nhan vien", "ho tro", "don hang", "thanh toan", "dat hang",
))

_reply_locks: dict[str, Lock] = defaultdict(Lock)


def _notify_rag_handoff_required(
    db: Session,
    *,
    conversation: Conversation,
    business_id: int,
    query_text: str,
) -> None:
    """Persist an urgent, owner-scoped alert when AI has no safe answer.

    An available responsible employee gets the alert alone. If nobody owns
    the conversation or that person is offline, the broadcast row makes the
    request visible to the team instead of silently losing it.
    """
    assigned_user_id = getattr(conversation, "assigned_user_id", None)
    user_id = (
        int(assigned_user_id)
        if assigned_user_id is not None
        and manager.is_user_connected(business_id=business_id, user_id=int(assigned_user_id))
        else None
    )
    create_notification(
        db,
        business_id=business_id,
        user_id=user_id,
        kind="rag_handoff_required",
        title="AI cần nhân viên hỗ trợ hội thoại",
        body=("AI chưa có đủ dữ liệu để trả lời: " + " ".join(str(query_text or "").split())[:280]),
        metadata={
            "conversation_id": int(conversation.id),
            "customer_id": int(conversation.customer_id),
            "reason": "no_rag_context",
        },
    )
    db.commit()


def _schedule_saved_message_event(db: Session, message_id: int | None) -> None:
    """Publish a just-persisted bot message to the CRM WebSocket.

    Keep the event shape aligned with ``GET /conversations/{id}/messages`` so
    the frontend can upsert it without a second request.  This is best effort:
    a disconnected browser must never make a successful provider delivery
    fail.
    """
    if not message_id:
        return
    try:
        row = db.query(Message).filter(Message.id == int(message_id)).first()
        if row is None:
            return
        business_id = getattr(row.conversation, "business_id", None)
        if business_id is None:
            return
        schedule_broadcast(
            {
                "type": "message_created",
                "conversation_id": row.conversation_id,
                "message": {
                    "message_id": row.id,
                    "conversation_id": row.conversation_id,
                    "channel": row.channel,
                    "external_user_id": row.external_user_id,
                    "external_message_id": row.external_message_id,
                    "direction": row.direction,
                    "content": row.content,
                    "media_type": row.media_type,
                    "media_url": row.media_url,
                    "raw_payload": row.raw_payload,
                    "received_at": row.received_at,
                    "sender_type": row.sender_type,
                    "status": row.status,
                    "attachments": [],
                },
            },
            business_id=int(business_id),
        )
    except Exception:
        # Realtime is an enhancement to the durable message write.  Logging
        # keeps failures diagnosable without taking down the bot reply.
        logger.warning("Could not publish auto-reply realtime event", exc_info=True)


def _reply_metadata(
    source_document_ids: list[int] | None,
    auto_reply_key: str | None,
    extra_metadata: dict | None = None,
) -> dict:
    metadata = {"rag_source_document_ids": source_document_ids or []}
    if auto_reply_key:
        metadata["auto_reply_key"] = auto_reply_key
        parts = auto_reply_key.split(":")
        if len(parts) >= 4 and parts[0] == "inbound":
            metadata["correlation_id"] = auto_reply_key
            metadata["inbound_message_id"] = parts[3]
            if len(parts) >= 5:
                metadata["route"] = parts[4]
    if extra_metadata:
        # Callers provide server-generated trace metadata only. Core
        # correlation fields above remain authoritative.
        for key, value in extra_metadata.items():
            if key not in metadata:
                metadata[key] = value
    return metadata


def _record_duplicate_reply_attempt(
    db: Session,
    *,
    business_id: int,
    conversation_id: int,
    auto_reply_key: str,
) -> None:
    """Persist a redacted quality signal when an outbound is deduplicated."""
    try:
        record_audit(
            db,
            business_id=business_id,
            actor_type="system",
            action="chatbot_auto_reply_duplicate",
            resource_type="conversation",
            resource_id=conversation_id,
            correlation_id=auto_reply_key,
            metadata={"conversation_id": conversation_id, "auto_reply_key": auto_reply_key},
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Could not persist duplicate auto-reply quality signal", exc_info=True)


def _record_auto_reply_sent(
    db: Session,
    *,
    business_id: int,
    conversation_id: int,
    message_id: int,
    external_message_id: str | None,
    auto_reply_key: str | None,
) -> None:
    """Record a redacted outbound event for the unified inbound→bot trace."""
    record_audit(
        db,
        business_id=business_id,
        actor_type="bot",
        action="chatbot_auto_reply_sent",
        resource_type="message",
        resource_id=message_id,
        correlation_id=auto_reply_key,
        metadata={
            "conversation_id": conversation_id,
            "external_message_id": external_message_id,
            "route": (auto_reply_key.split(":", 4)[4] if auto_reply_key and auto_reply_key.startswith("inbound:") and len(auto_reply_key.split(":", 4)) == 5 else None),
        },
    )


def _send_channel_reply(
    *,
    db: Session,
    conversation_id: int,
    channel: str,
    recipient_id: str,
    text: str,
    business_id: int,
) -> dict:
    """Send one reply through the tenant-owned channel connection."""
    if channel == "facebook":
        return send_facebook_message(
            recipient_id=recipient_id,
            text=text,
            db=db,
            business_id=business_id,
        )
    if channel == "instagram":
        return send_instagram_message(
            recipient_id=recipient_id,
            text=text,
            db=db,
            business_id=business_id,
        )
    if channel == "telegram":
        return send_telegram_message(
            db=db,
            business_id=business_id,
            conversation_id=conversation_id,
            recipient_id=recipient_id,
            text=text,
        )
    if channel == "zalo":
        return send_zalo_message(
            db=db,
            business_id=business_id,
            conversation_id=conversation_id,
            recipient_id=recipient_id,
            text=text,
        )
    raise ValueError(f"Unsupported auto-reply channel: {channel}")


def _get_conversation_recipient(
    db: Session,
    conversation_id: int,
    business_id: int,
) -> tuple[str, str]:
    """Return channel and platform recipient id for a conversation."""
    row = db.execute(
        text(
            """
            SELECT cv.channel, c.external_user_id
            FROM conversations cv
            JOIN customers c ON c.id = cv.customer_id
            WHERE cv.id = :conversation_id
              AND cv.business_id = :business_id
              AND c.business_id = :business_id
            LIMIT 1
            """
        ),
        {"conversation_id": conversation_id, "business_id": business_id},
    ).mappings().first()

    if row is None or not row["external_user_id"]:
        raise ValueError(
            f"Không tìm thấy recipient cho conversation {conversation_id}."
        )

    return row["channel"], str(row["external_user_id"])


def _save_auto_reply_outbound(
    db: Session,
    conversation_id: int,
    channel: str,
    recipient_id: str,
    external_message_id: str | None,
    content: str,
    meta_response: dict,
    source_document_ids: list[int] | None = None,
    auto_reply_key: str | None = None,
    extra_metadata: dict | None = None,
) -> None:
    """Persist the external reply so it appears in the CRM inbox."""
    conversation_business_id = db.query(Conversation.business_id).filter(
        Conversation.id == conversation_id,
    ).scalar()
    if auto_reply_key:
        # A claimed row is updated after delivery.  The unique key protects
        # retries even when the provider returns a different message id.
        updated = db.query(Message).filter(Message.auto_reply_key == auto_reply_key).first()
        if updated is not None:
            updated.external_message_id = external_message_id
            updated.content = content
            updated.raw_payload = meta_response
            updated.metadata_ = _reply_metadata(
                source_document_ids, auto_reply_key, extra_metadata
            )
            updated.status = "sent"
            updated.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
            if conversation_business_id is not None:
                _record_auto_reply_sent(
                    db,
                    business_id=int(conversation_business_id),
                    conversation_id=conversation_id,
                    message_id=updated.id,
                    external_message_id=external_message_id,
                    auto_reply_key=auto_reply_key,
                )
            db.commit()
            _schedule_saved_message_event(db, updated.id)
            return
    db.execute(
        text(
            """
            INSERT INTO messages (
                conversation_id,
                channel,
                external_user_id,
                external_message_id,
                auto_reply_key,
                sender_type,
                direction,
                content,
                raw_payload,
                metadata
            )
            VALUES (
                :conversation_id,
                :channel,
                :external_user_id,
                :external_message_id,
                :auto_reply_key,
                'bot',
                'outbound',
                :content,
                CAST(:raw_payload AS JSONB),
                CAST(:metadata AS JSONB)
            )
            ON CONFLICT (external_message_id) DO NOTHING
            """
        ),
        {
            "conversation_id": conversation_id,
            "channel": channel,
            "external_user_id": recipient_id,
            "external_message_id": external_message_id,
            "auto_reply_key": auto_reply_key,
            "content": content,
            "raw_payload": json.dumps(meta_response, ensure_ascii=False, default=str),
            "metadata": json.dumps(
                _reply_metadata(source_document_ids, auto_reply_key, extra_metadata),
                ensure_ascii=False,
            ),
        },
    )
    db.commit()
    if auto_reply_key:
        sent = db.query(Message).filter(Message.auto_reply_key == auto_reply_key).first()
        if sent is not None:
            if conversation_business_id is not None:
                _record_auto_reply_sent(
                    db,
                    business_id=int(conversation_business_id),
                    conversation_id=conversation_id,
                    message_id=sent.id,
                    external_message_id=external_message_id,
                    auto_reply_key=auto_reply_key,
                )
                db.commit()
            _schedule_saved_message_event(db, sent.id)
            return

    # ``auto_reply_key`` is present for normal inbound-triggered replies.  The
    # fallback also covers deterministic replies created by older integrations
    # that only have the provider message id.
    sent = db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.external_message_id == external_message_id,
        Message.sender_type == "bot",
        Message.direction == "outbound",
    ).order_by(Message.id.desc()).first()
    _schedule_saved_message_event(db, sent.id if sent is not None else None)


def _claim_auto_reply(
    db: Session,
    *,
    conversation_id: int,
    channel: str,
    recipient_id: str,
    content: str,
    business_id: int,
    auto_reply_key: str,
) -> bool:
    """Claim one deterministic response before calling an external provider."""
    lock = _reply_locks[auto_reply_key]
    with lock:
        existing = db.query(Message).filter(Message.auto_reply_key == auto_reply_key).first()
        if existing is not None and existing.status in {"sending", "sent"}:
            _record_duplicate_reply_attempt(
                db,
                business_id=business_id,
                conversation_id=conversation_id,
                auto_reply_key=auto_reply_key,
            )
            return False
        if existing is None:
            db.add(Message(
                conversation_id=conversation_id,
                channel=channel,
                external_user_id=recipient_id,
                auto_reply_key=auto_reply_key,
                sender_type="bot",
                direction="outbound",
                content=content,
                status="sending",
                metadata_={"auto_reply_key": auto_reply_key, "business_id": business_id},
            ))
        else:
            existing.status = "sending"
            existing.content = content
        try:
            db.commit()
        except IntegrityError:
            # Another process may have won the unique key.  Recover the
            # session and let that process own the delivery.
            db.rollback()
            _record_duplicate_reply_attempt(
                db,
                business_id=business_id,
                conversation_id=conversation_id,
                auto_reply_key=auto_reply_key,
            )
            return False
        except Exception:
            db.rollback()
            raise
        return True


def _mark_auto_reply_failed(db: Session, auto_reply_key: str, error: Exception) -> None:
    row = db.query(Message).filter(Message.auto_reply_key == auto_reply_key).first()
    if row is None:
        return
    row.status = "failed"
    # Keep provider/customer payloads out of the message metadata and logs.
    row.metadata_ = {"auto_reply_key": auto_reply_key, "error_type": type(error).__name__}
    db.commit()


def _format_vnd(value: object) -> str:
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal("0")
    return f"{amount:,.0f}".replace(",", ".")


def format_product_catalog_reply(products: list[Product]) -> str:
    """Format tenant-owned active products as a safe no-RAG fallback."""
    if not products:
        return NO_PRODUCT_CATALOG_REPLY

    lines = ["Mình đang có các sản phẩm:"]
    for product in products:
        available = max(
            int(product.stock_quantity or 0) - int(product.reserved_quantity or 0),
            0,
        )
        stock_label = f"còn {available}" if available else "hết hàng"
        lines.append(
            f"- {product.name} — {_format_vnd(product.price)} đồng ({stock_label})"
        )
    lines.append("Bạn muốn xem sản phẩm nào để mình tư vấn thêm nhé?")
    return "\n".join(lines)


def build_product_catalog_reply(db: Session, business_id: int, limit: int = 10) -> str:
    """Read the shop's active catalog for product-discovery fallback replies."""
    products = db.query(Product).filter(
        Product.business_id == business_id,
        Product.status == "active",
    ).order_by(Product.name.asc(), Product.id.asc()).limit(limit).all()
    return format_product_catalog_reply(products)


def _fold_text(value: object) -> str:
    """Normalize Vietnamese customer text for small deterministic routers."""
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    normalized = normalized.replace("đ", "d")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", normalized).split())


def _has_any_term(text: str, terms: tuple[str, ...] | set[str]) -> bool:
    return any(term in text for term in terms)


def _product_hint(text: str) -> str:
    """Extract a human-readable product hint without guessing a product."""
    original = " ".join(str(text or "").strip().split())
    folded = _fold_text(original)
    if not folded:
        return ""
    tokens = [
        token for token in folded.split()
        if token not in _PRODUCT_HINT_STOP_WORDS
        and token not in _NON_PRODUCT_HINT_WORDS
        and not token.isdigit()
        and len(token) >= 2
    ]
    return " ".join(tokens[:5])


def _is_product_fact_question(text: str, *, conversation_id: int | None = None) -> bool:
    folded = _fold_text(text)
    if not folded:
        return False
    if _has_any_term(folded, _STOCK_TERMS):
        # ``is_browsing_request`` also recognises the phrase "còn hàng".  A
        # stock question must still reach the exact-product/follow-up router,
        # otherwise a bare "còn hàng không?" falls through to RAG.
        return True
    if _has_any_term(folded, _PRICE_TERMS):
        # Broad catalogue questions are handled by the catalogue route below;
        # only named/follow-up questions need exact product lookup.
        return not is_browsing_request(text) or bool(_product_hint(text))
    return False


def _is_specific_product_lookup(text: str) -> bool:
    """Identify "shop có laptop không?" without treating policies as products."""
    folded = _fold_text(text)
    if not folded or _has_any_term(folded, _DELIVERY_TERMS + _RETURN_TERMS):
        return False
    if _has_any_term(folded, _RECOMMENDATION_TERMS):
        return False
    if is_browsing_request(text):
        return False
    # A code/name followed by a question, or the common "có X không" form.
    return bool(
        re.search(r"\bco\s+.+\s+khong\b", folded)
        or re.search(r"\b(?:tim|xem|tu van|mua)\s+.+", folded)
    )


def _find_exact_product(
    db: Session,
    business_id: int,
    text: str,
    *,
    conversation_id: int | None = None,
) -> tuple[Product | None, str]:
    """Resolve an explicit product name/SKU, then a short conversational follow-up.

    We intentionally do not use fuzzy semantic matching for an explicit unknown
    product.  Returning a nearby product is worse than asking the customer to
    correct a typo, and was the reason ``serum01`` produced the full catalogue.
    """
    folded = _fold_text(text)
    hint = _product_hint(text)
    try:
        products = db.query(Product).filter(
            Product.business_id == business_id,
            Product.status == "active",
        ).order_by(Product.id.asc()).all()
        products = list(products)
    except Exception:
        return None, hint

    matches: list[tuple[int, int, Product]] = []
    for product in products:
        for alias in product_aliases(product):
            alias_folded = _fold_text(alias)
            if len(alias_folded) < 3:
                continue
            if alias_folded in folded:
                matches.append((len(alias_folded), -int(product.id or 0), product))
    if matches:
        _length, _id, product = max(matches)
        return product, hint

    # Follow-ups such as “sản phẩm lúc nãy còn hàng không?” may omit the
    # product name.  The resolver looks only at the customer's previous
    # messages, never at the bot's catalogue response.
    if conversation_id is not None and not hint:
        try:
            product = resolve_product(
                db,
                business_id=business_id,
                text=text,
                conversation_id=conversation_id,
            )
            if product is not None:
                return product, hint
        except Exception:
            logger.debug("Could not resolve conversational product", exc_info=True)
    return None, hint


def _format_product_fact_reply(product: Product, folded_query: str) -> str:
    available = max(
        int(product.stock_quantity or 0) - int(product.reserved_quantity or 0),
        0,
    )
    name = product.name
    price_requested = _has_any_term(folded_query, _PRICE_TERMS)
    stock_requested = _has_any_term(folded_query, _STOCK_TERMS)
    if price_requested and stock_requested:
        return f"{name} hiện có giá {_format_vnd(product.price)} đồng và còn {available} sản phẩm."
    if price_requested:
        return f"{name} hiện có giá {_format_vnd(product.price)} đồng."
    return f"{name} hiện còn {available} sản phẩm." if available else f"{name} hiện đã hết hàng."


def _recommendation_reply(
    db: Session,
    *,
    business_id: int,
    query_text: str,
) -> str | None:
    """Recommend only products carrying an explicit matching attribute."""
    folded_query = _fold_text(query_text)
    query_terms = {
        token
        for token in folded_query.split()
        if len(token) >= 3 and token not in _PRODUCT_HINT_STOP_WORDS and token not in {"phu", "hop"}
    }
    if not query_terms:
        return None

    try:
        products = db.query(Product).filter(
            Product.business_id == business_id,
            Product.status == "active",
        ).order_by(Product.id.asc()).all()
    except Exception:
        return None

    matches: list[tuple[int, Product]] = []
    for product in products:
        raw_attributes = (product.metadata_ or {}).get("attributes") if isinstance(product.metadata_, dict) else None
        if not isinstance(raw_attributes, dict):
            continue
        values = [
            _fold_text(value)
            for raw in raw_attributes.values()
            for value in (raw if isinstance(raw, list) else [raw])
            if str(value or "").strip()
        ]
        score = 0
        for value in values:
            if value in folded_query:
                score += 3
            elif query_terms.intersection(value.split()):
                score += 1
        if score:
            matches.append((score, product))

    if not matches:
        return None
    matches.sort(key=lambda item: (-item[0], item[1].id or 0))
    lines = []
    for _score, product in matches[:3]:
        available = max(int(product.stock_quantity or 0) - int(product.reserved_quantity or 0), 0)
        lines.append(f"- {product.name} — {_format_vnd(product.price)} đồng (còn {available})")
    return (
        "Mình tìm thấy một số sản phẩm phù hợp với nhu cầu của bạn:\n"
        + "\n".join(lines)
        + "\nBạn muốn xem sản phẩm nào để mình tư vấn thêm?"
    )


def _deterministic_customer_reply(
    db: Session,
    *,
    business_id: int,
    conversation_id: int,
    query_text: str,
) -> tuple[str, str] | None:
    """Return a safe reply and route for questions that must not enter RAG."""
    folded = _fold_text(query_text)
    # Policy questions are checked after retrieval.  If the knowledge base
    # contains a matching policy, the LLM may summarize it; if not, the caller
    # sends the explicit missing-policy reply instead of a product catalogue.
    if _policy_kind(query_text):
        return None

    if (
        _has_any_term(folded, _PRICE_TERMS)
        and not _product_hint(query_text)
        and (
            not is_browsing_request(query_text)
            or "tong" in folded
            or "thanh tien" in folded
        )
    ):
        return AMBIGUOUS_PRICE_REPLY, "product_price_clarification"
    if _has_any_term(folded, _RECOMMENDATION_TERMS):
        recommendation = _recommendation_reply(
            db,
            business_id=business_id,
            query_text=query_text,
        )
        if recommendation:
            return recommendation, "product_recommendation"
        # If no product carries a matching attribute, continue through the
        # knowledge-base route so the assistant can ask a clarifying question
        # instead of inventing suitability.
        return None

    product_fact = _is_product_fact_question(query_text, conversation_id=conversation_id)
    specific_lookup = _is_specific_product_lookup(query_text)
    if not product_fact and not specific_lookup:
        return None

    product, hint = _find_exact_product(
        db,
        business_id,
        query_text,
        conversation_id=conversation_id,
    )
    if product is not None and product_fact:
        return _format_product_fact_reply(product, folded), "product_fact"
    if product is not None and specific_lookup:
        return (
            f"Mình tìm thấy {product.name}, giá {_format_vnd(product.price)} đồng, "
            f"hiện còn {max(int(product.stock_quantity or 0) - int(product.reserved_quantity or 0), 0)} sản phẩm.",
            "product_lookup",
        )
    if product_fact or specific_lookup:
        if product_fact and not hint:
            return AMBIGUOUS_STOCK_REPLY, "product_stock_clarification"
        if hint:
            return PRODUCT_NOT_FOUND_WITH_HINT.format(hint=hint), "product_not_found"
        return PRODUCT_NOT_FOUND_REPLY, "product_not_found"
    return None


def _chunk_supports_policy(chunks: list, policy: str) -> bool:
    """Reject semantically-near but factually-unrelated catalogue chunks."""
    terms = _DELIVERY_TERMS if policy == "delivery" else _RETURN_TERMS
    # Test doubles and legacy retrievers may not expose chunk text.  In that
    # case keep the old RAG path; real chunks always contain a string.
    known_text = [getattr(chunk, "content", None) for chunk in chunks]
    if not any(isinstance(content, str) and content.strip() for content in known_text):
        return True
    return any(
        isinstance(content, str) and _has_any_term(_fold_text(content), terms)
        for content in known_text
    )


def _policy_kind(text: str) -> str | None:
    folded = _fold_text(text)
    if _has_any_term(folded, _DELIVERY_TERMS):
        return "delivery"
    if _has_any_term(folded, _RETURN_TERMS):
        return "return"
    return None


def send_text_reply(
    *,
    db: Session,
    conversation_id: int,
    channel: str,
    text: str,
    business_id: int,
    auto_reply_key: str | None = None,
    extra_metadata: dict | None = None,
) -> dict:
    """Send and persist a deterministic non-RAG reply on the conversation channel."""
    stored_channel, recipient_id = _get_conversation_recipient(
        db,
        conversation_id,
        business_id,
    )
    if stored_channel != channel:
        logger.warning(
            "Conversation channel mismatch: event=%s, database=%s",
            channel,
            stored_channel,
        )
        channel = stored_channel
    if auto_reply_key and not _claim_auto_reply(
        db,
        conversation_id=conversation_id,
        channel=channel,
        recipient_id=recipient_id,
        content=text,
        business_id=business_id,
        auto_reply_key=auto_reply_key,
    ):
        existing = db.query(Message).filter(Message.auto_reply_key == auto_reply_key).first()
        return {
            "message_id": existing.external_message_id if existing is not None else None,
            "idempotent": True,
        }
    try:
        response = _send_channel_reply(
            db=db,
            conversation_id=conversation_id,
            channel=channel,
            recipient_id=recipient_id,
            text=text,
            business_id=business_id,
        )
        save_kwargs = {
            "db": db,
            "conversation_id": conversation_id,
            "channel": channel,
            "recipient_id": recipient_id,
            "external_message_id": response.get("message_id"),
            "content": text,
            "meta_response": response,
            "source_document_ids": [],
        }
        if extra_metadata:
            save_kwargs["extra_metadata"] = extra_metadata
        if auto_reply_key:
            save_kwargs["auto_reply_key"] = auto_reply_key
        _save_auto_reply_outbound(**save_kwargs)
    except Exception as error:
        if auto_reply_key:
            _mark_auto_reply_failed(db, auto_reply_key, error)
        raise
    return response


def send_text_reply_background(
    *,
    conversation_id: int,
    channel: str,
    text: str,
    business_id: int,
    auto_reply_key: str | None = None,
) -> None:
    """Send a deterministic reply without delaying the webhook response."""

    def worker() -> None:
        try:
            with tenant_session(schema_name_for(business_id)) as db:
                send_text_reply(
                    db=db,
                    conversation_id=conversation_id,
                    channel=channel,
                    text=text,
                    business_id=business_id,
                    auto_reply_key=auto_reply_key,
                )
        except Exception:
            logger.exception(
                "Deterministic reply failed for conversation %d",
                conversation_id,
            )

    Thread(target=worker, daemon=True).start()


def get_auto_reply_enabled(db: Session, business_id: int) -> bool:
    setting = db.query(BusinessSetting).filter(
        BusinessSetting.business_id == business_id,
        BusinessSetting.key == AUTO_REPLY_SETTING_KEY,
    ).first()
    if setting is None:
        # Keep a configurable default for a fresh database. Once the user
        # changes the toggle, app_settings becomes the source of truth.
        return bool(settings.RAG_AUTO_REPLY_ENABLED)
    return setting.value.strip().lower() == "true"


def set_auto_reply_enabled(db: Session, enabled: bool, business_id: int) -> bool:
    value = "true" if enabled else "false"
    setting = db.query(BusinessSetting).filter(
        BusinessSetting.business_id == business_id,
        BusinessSetting.key == AUTO_REPLY_SETTING_KEY,
    ).first()
    if setting is None:
        setting = BusinessSetting(business_id=business_id, key=AUTO_REPLY_SETTING_KEY, value=value)
        db.add(setting)
    else:
        setting.value = value
    db.commit()
    logger.info("RAG Auto-reply toggled to: %s", enabled)
    return enabled


def process_rag_auto_reply(
    db: Session,
    conversation_id: int,
    channel: str,
    query_text: str,
    business_id: int,
    auto_reply_key: str | None = None,
    platform_db: Session | None = None,
) -> bool:
    """
    Tự động tra cứu RAG và gửi tin nhắn phản hồi cho khách hàng.
    """
    config = db.query(ChatbotConfig).filter(ChatbotConfig.business_id == business_id).first()
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.business_id == business_id,
    ).first()
    if not isinstance(config, ChatbotConfig):
        config = None
    top_k = int(config.top_k if config and isinstance(config.top_k, (int, float)) and config.top_k else 5)
    similarity_threshold = float(
        config.similarity_threshold
        if config and isinstance(config.similarity_threshold, (int, float))
        else 0.3
    )
    bandit_choice: ChatbotBanditChoice | None = None

    def send_reply(text_value: str) -> dict:
        kwargs = {
            "db": db,
            "conversation_id": conversation_id,
            "channel": channel,
            "text": text_value,
            "business_id": business_id,
        }
        if auto_reply_key:
            kwargs["auto_reply_key"] = auto_reply_key
        if bandit_choice is not None:
            kwargs["extra_metadata"] = bandit_choice.message_metadata()
        return send_text_reply(**kwargs)

    with RagRunLog(
        "auto_reply",
        business_id=business_id,
        conversation_id=conversation_id,
        channel=channel,
        query_preview=(query_text or "")[:500],
        top_k=top_k,
    ) as run:
      if not get_auto_reply_enabled(db, business_id):
          logger.info(
              "Auto-reply skipped: disabled for conversation %d",
              conversation_id,
          )
          run.finish("skipped", phase="complete", reason="auto_reply_disabled")
          return False

      if not query_text or not query_text.strip():
          run.finish("skipped", phase="complete", reason="empty_query")
          return False

      if config is not None and config.enabled is False:
          run.finish("skipped", phase="complete", reason="chatbot_disabled")
          return False

      if conversation is None or conversation.bot_mode == "human":
          run.finish("skipped", phase="complete", reason="human_takeover")
          return False

      if not is_business_open(db, business_id):
          send_reply(OUT_OF_HOURS_REPLY)
          run.finish("outside_business_hours", phase="complete")
          return True

      try:
        deterministic_order_reply = customer_order_reply(
            db,
            business_id,
            conversation_id,
            query_text,
            platform_db=platform_db,
        )
        if deterministic_order_reply:
            send_reply(deterministic_order_reply)
            run.finish(
                "order_action",
                phase="complete",
                chunks_found=0,
                answer_chars=len(deterministic_order_reply),
            )
            return True

        # Combo savings are calculated from the live product catalog.  Do not
        # let the language model infer prices from an old knowledge chunk.
        from app.services.product_pricing import combo_price_comparison_reply

        combo_reply = combo_price_comparison_reply(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            text=query_text,
        )
        if combo_reply:
            send_reply(combo_reply)
            run.finish(
                "combo_price_comparison",
                phase="complete",
                chunks_found=0,
                answer_chars=len(combo_reply),
            )
            return True

        # Product price/stock and exact product lookup are read from the live
        # catalogue.  This prevents an unrelated RAG chunk from turning a
        # typo such as ``serum01`` into a full product-list answer.
        deterministic_reply = _deterministic_customer_reply(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            query_text=query_text,
        )
        if deterministic_reply:
            reply_text, route = deterministic_reply
            send_reply(reply_text)
            run.finish(
                route,
                phase="complete",
                chunks_found=0,
                answer_chars=len(reply_text),
            )
            return True

        policy_kind = _policy_kind(query_text)
        recommendation_question = _has_any_term(_fold_text(query_text), _RECOMMENDATION_TERMS)

        # Broad product-discovery questions should show the live catalog
        # deterministically.  Letting them enter RAG first can return a
        # generic greeting even when the knowledge base has unrelated chunks.
        # Policy and recommendation questions are deliberately excluded: the
        # phrase "có ... không" also matches those questions, but a catalogue
        # dump is not an answer to them.
        if is_browsing_request(query_text) and not policy_kind and not recommendation_question:
            catalog_reply = build_product_catalog_reply(db, business_id)
            send_reply(catalog_reply)
            run.finish(
                "catalog_direct",
                phase="complete",
                chunks_found=0,
                answer_chars=len(catalog_reply),
            )
            return True

        run.update(phase="retrieve")
        query_meta = query_metadata(query_text)
        logger.info(
            "Executing RAG auto-reply for conversation %d (query_chars=%s query_hash=%s)",
            conversation_id,
            query_meta["query_chars"],
            query_meta["query_hash"],
        )

        # 1. Retrieve
        retrieval_started = perf_counter()
        chunks = retrieve(
            query=query_text,
            db=db,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
            business_id=business_id,
        )
        run.update(
            retrieval_topic=infer_query_topic(query_text),
            retrieval_ms=round((perf_counter() - retrieval_started) * 1000, 2),
            retrieval_top_similarity=round(max((c.similarity for c in chunks), default=0), 4),
        )
        if policy_kind and chunks and not _chunk_supports_policy(chunks, policy_kind):
            reply_text = NO_DELIVERY_POLICY_REPLY if policy_kind == "delivery" else NO_RETURN_POLICY_REPLY
            send_reply(reply_text)
            run.finish(
                f"{policy_kind}_policy_missing",
                phase="complete",
                chunks_found=len(chunks),
                answer_chars=len(reply_text),
            )
            return True
        if recommendation_question and chunks:
            # A generic catalogue chunk is not evidence that a product is
            # suitable for a customer's stated need.
            query_terms = [
                token
                for token in _fold_text(query_text).split()
                if len(token) >= 3
                and token not in _PRODUCT_HINT_STOP_WORDS
                and token not in _NON_PRODUCT_HINT_WORDS
                and token not in {"phu", "hop"}
            ]
            if query_terms and not any(
                any(term in _fold_text(getattr(chunk, "content", "")) for term in query_terms)
                for chunk in chunks
            ):
                send_reply(NO_RECOMMENDATION_REPLY)
                run.finish(
                    "recommendation_missing",
                    phase="complete",
                    chunks_found=len(chunks),
                    answer_chars=len(NO_RECOMMENDATION_REPLY),
                )
                return True
        if not chunks:
            if policy_kind:
                reply_text = NO_DELIVERY_POLICY_REPLY if policy_kind == "delivery" else NO_RETURN_POLICY_REPLY
                send_reply(reply_text)
                run.finish(
                    f"{policy_kind}_policy_missing",
                    phase="complete",
                    chunks_found=0,
                    answer_chars=len(reply_text),
                )
                return True
            if recommendation_question:
                send_reply(NO_RECOMMENDATION_REPLY)
                run.finish(
                    "recommendation_missing",
                    phase="complete",
                    chunks_found=0,
                    answer_chars=len(NO_RECOMMENDATION_REPLY),
                )
                return True
            if is_browsing_request(query_text):
                catalog_reply = build_product_catalog_reply(db, business_id)
                send_reply(catalog_reply)
                logger.info(
                    "Product catalog fallback sent via %s to conversation %d",
                    channel,
                    conversation_id,
                )
                run.finish(
                    "catalog_fallback",
                    phase="complete",
                    chunks_found=0,
                    answer_chars=len(catalog_reply),
                )
                return True
            logger.warning(
                "Auto-reply skipped: no relevant RAG chunks for conversation %d, query=%r",
                conversation_id,
                query_text[:100],
            )
            _notify_rag_handoff_required(
                db,
                conversation=conversation,
                business_id=business_id,
                query_text=query_text,
            )
            run.finish("no_context", phase="complete", chunks_found=0)
            return False

        # Live experimentation is explicitly opt-in. Only an active policy
        # bound to chatbot_auto_reply with reviewed arm controls can create a
        # decision. Invalid/missing policies safely fall back to the normal
        # RAG path.
        try:
            bandit_choice = select_chatbot_reply_choice(
                db,
                business_id=business_id,
                conversation_id=conversation_id,
                channel=channel,
                query_topic=infer_query_topic(query_text),
                auto_reply_key=auto_reply_key,
            )
        except Exception:
            # Experimentation is an optional enhancement. A missing legacy
            # table or malformed policy must never disable customer replies.
            db.rollback()
            bandit_choice = None
            logger.warning(
                "Chatbot bandit selection failed; using the default reply path",
                exc_info=True,
            )
        if bandit_choice and bandit_choice.max_context_chunks:
            chunks = chunks[: bandit_choice.max_context_chunks]

        # 2. Build prompt
        run.update(
            phase="build_prompt",
            chunks_found=len(chunks),
            source_document_ids=sorted({c.document_id for c in chunks}),
            top_similarity=round(max((c.similarity for c in chunks), default=0), 4),
        )
        memory = build_agent_memory(db, business_id, conversation_id)
        runtime_system_prompt = config.system_prompt if config and config.system_prompt else None
        if bandit_choice is not None:
            style_instruction = response_style_instruction(bandit_choice.response_style)
            if style_instruction:
                runtime_system_prompt = "\n\n".join(
                    value for value in (runtime_system_prompt, style_instruction) if value
                )
        messages = build_prompt(
            query=query_text,
            chunks=chunks,
            conversation_history=memory["history"][:-1],
            system_prompt=runtime_system_prompt,
        )

        # 3. Call LLM
        run.update(phase="llm")
        try:
            record_quota_usage(
                db,
                business_id,
                "ai_calls",
                1,
                idempotency_key=f"rag-llm:{run.run_id}",
            )
            estimated_cost = estimate_ai_cost(messages)
            if estimated_cost > 0:
                # Reserve the conservative estimate before the provider call,
                # so an exhausted AI budget cannot still trigger billable work.
                # The run id makes webhook retries idempotent.
                record_quota_usage(
                    db,
                    business_id,
                    "ai_cost",
                    estimated_cost,
                    idempotency_key=f"rag-cost:{run.run_id}",
                )
                run.update(estimated_ai_cost=float(estimated_cost))
            # Persist the reservation before the external provider call so a
            # timeout or process restart cannot let a billable retry bypass
            # the tenant quota.
            db.commit()
        except QuotaExceededError as exc:
            db.rollback()
            logger.warning(
                "AI quota exhausted for business %d, conversation %d, resource=%s",
                business_id,
                conversation_id,
                exc.resource,
            )
            run.finish("quota_exceeded", phase="complete", quota=exc.detail)
            return False
        answer = call_llm(messages)
        if not answer or not answer.strip():
            logger.warning("Empty LLM answer for RAG auto-reply")
            run.finish("error", phase="complete", reason="empty_llm_answer", answer_chars=0)
            return False

        # 4. Resolve the platform recipient and send the reply.
        stored_channel, recipient_id = _get_conversation_recipient(
            db,
            conversation_id,
            business_id,
        )
        if stored_channel != channel:
            logger.warning(
                "Conversation channel mismatch: event=%s, database=%s",
                channel,
                stored_channel,
            )
            channel = stored_channel

        if auto_reply_key and not _claim_auto_reply(
            db,
            conversation_id=conversation_id,
            channel=channel,
            recipient_id=recipient_id,
            content=answer,
            business_id=business_id,
            auto_reply_key=auto_reply_key,
        ):
            run.finish("idempotent", phase="complete", chunks_found=len(chunks))
            return True
        try:
            meta_response = _send_channel_reply(
                db=db,
                conversation_id=conversation_id,
                channel=channel,
                recipient_id=recipient_id,
                text=answer,
                business_id=business_id,
            )
        except Exception as error:
            if auto_reply_key:
                _mark_auto_reply_failed(db, auto_reply_key, error)
            raise
        logger.info(
            "RAG auto-reply sent via %s to conversation %d",
            channel,
            conversation_id,
        )

        save_kwargs = {
            "db": db,
            "conversation_id": conversation_id,
            "channel": channel,
            "recipient_id": recipient_id,
            "external_message_id": meta_response.get("message_id"),
            "content": answer,
            "meta_response": meta_response,
            "source_document_ids": sorted({chunk.document_id for chunk in chunks}),
        }
        if auto_reply_key:
            save_kwargs["auto_reply_key"] = auto_reply_key
        if bandit_choice is not None:
            save_kwargs["extra_metadata"] = bandit_choice.message_metadata()
        _save_auto_reply_outbound(**save_kwargs)
        logger.info(
            "Auto-reply completed for conversation %d, external_message_id=%s",
            conversation_id,
            meta_response.get("message_id"),
        )
        run.finish("success", phase="complete", answer_chars=len(answer))
        return True

      except Exception as e:
          logger.exception("RAG auto-reply error: %s", str(e))
          run.finish(
              "error",
              phase="complete",
              error_type=type(e).__name__,
              error=str(e)[:1000],
          )
          return False

    return False


def process_rag_auto_reply_background(
    conversation_id: int,
    channel: str,
    query_text: str,
    business_id: int,
    auto_reply_key: str | None = None,
) -> None:
    """Run RAG auto-reply off the webhook request path."""

    def worker() -> None:
        try:
            with PlatformSessionLocal() as platform_db:
                with tenant_session(schema_name_for(business_id)) as db:
                    logger.info(
                        "Auto-reply worker started for conversation %d, channel=%s",
                        conversation_id,
                        channel,
                    )
                    process_rag_auto_reply(
                        db=db,
                        conversation_id=conversation_id,
                        channel=channel,
                        query_text=query_text,
                        business_id=business_id,
                        auto_reply_key=auto_reply_key,
                        platform_db=platform_db,
                    )
        except Exception:
            # Background work must never leak an unhandled thread exception
            # into request/test runners. The operation is already recorded by
            # RagRunLog; keep the failure visible in application logs.
            logger.exception(
                "Auto-reply worker failed for conversation %d",
                conversation_id,
            )
        finally:
            logger.info(
                "Auto-reply worker finished for conversation %d",
                conversation_id,
            )

    Thread(target=worker, daemon=True).start()
