"""
Auto Reply Service – Tự động trả lời tin nhắn từ RAG knowledge base khi có tin nhắn inbound.
"""

import json
import logging
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from threading import Lock, Thread

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import SessionLocal
from app.models.business_setting import BusinessSetting
from app.models.chatbot import ChatbotConfig
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.sales import Product

from app.rag.retriever import retrieve
from app.rag.prompt_builder import build_prompt
from app.rag.llm_caller import call_llm
from app.rag.run_logger import RagRunLog
from app.services.facebook_service import send_facebook_message
from app.services.instagram_service import send_instagram_message
from app.services.telegram_service import send_telegram_message
from app.services.zalo_service import send_zalo_message
from app.services.customer_collection_flow import is_browsing_request
from app.services.chatbot_agent import build_agent_memory, is_business_open
from app.services.customer_order_service import customer_order_reply
from app.services.audit_service import record_audit
from app.services.quota_service import QuotaExceededError, estimate_ai_cost, record_quota_usage

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

_reply_locks: dict[str, Lock] = defaultdict(Lock)


def _reply_metadata(source_document_ids: list[int] | None, auto_reply_key: str | None) -> dict:
    metadata = {"rag_source_document_ids": source_document_ids or []}
    if auto_reply_key:
        metadata["auto_reply_key"] = auto_reply_key
        parts = auto_reply_key.split(":")
        if len(parts) >= 4 and parts[0] == "inbound":
            metadata["correlation_id"] = auto_reply_key
            metadata["inbound_message_id"] = parts[3]
            if len(parts) >= 5:
                metadata["route"] = parts[4]
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
            updated.metadata_ = _reply_metadata(source_document_ids, auto_reply_key)
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
            "metadata": json.dumps(_reply_metadata(source_document_ids, auto_reply_key), ensure_ascii=False),
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


def send_text_reply(
    *,
    db: Session,
    conversation_id: int,
    channel: str,
    text: str,
    business_id: int,
    auto_reply_key: str | None = None,
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
        db = SessionLocal()
        try:
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
        finally:
            db.close()

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
        return send_text_reply(**kwargs)

    with RagRunLog(
        "auto_reply",
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

        # Broad product-discovery questions should show the live catalog
        # deterministically.  Letting them enter RAG first can return a
        # generic greeting even when the knowledge base has unrelated chunks.
        if is_browsing_request(query_text):
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
        logger.info("Executing RAG auto-reply for conversation %d (query: %s)", conversation_id, query_text[:50])

        # 1. Retrieve
        chunks = retrieve(
            query=query_text,
            db=db,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
            business_id=business_id,
        )
        if not chunks:
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
            run.finish("no_context", phase="complete", chunks_found=0)
            return False

        # 2. Build prompt
        run.update(
            phase="build_prompt",
            chunks_found=len(chunks),
            source_document_ids=sorted({c.document_id for c in chunks}),
            top_similarity=round(max((c.similarity for c in chunks), default=0), 4),
        )
        memory = build_agent_memory(db, business_id, conversation_id)
        messages = build_prompt(
            query=query_text,
            chunks=chunks,
            conversation_history=memory["history"][:-1],
            system_prompt=config.system_prompt if config and config.system_prompt else None,
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
        db = SessionLocal()
        try:
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
            db.close()
            logger.info(
                "Auto-reply worker finished for conversation %d",
                conversation_id,
            )

    Thread(target=worker, daemon=True).start()
