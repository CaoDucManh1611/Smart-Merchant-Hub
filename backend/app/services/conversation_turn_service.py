"""Coalesce nearby inbound messages into one durable chatbot turn."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from time import perf_counter

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.conversation import Conversation
from app.models.message import Message
from app.services.job_service import enqueue_job

logger = logging.getLogger(__name__)
SHORTCUT_COMMAND = re.compile(r"^(/(?:[a-zA-Z0-9_-]+))(?:@[a-zA-Z0-9_]+)?$")


def schedule_chatbot_turn(db: Session, *, business_id: int, conversation_id: int, message_id: int) -> None:
    wait = max(1, min(int(settings.CONVERSATION_TURN_WAIT_SECONDS), 30))
    enqueue_job(
        db,
        business_id=business_id,
        kind="chatbot.reply_turn",
        payload={"conversation_id": conversation_id, "message_id": message_id},
        idempotency_key=f"chatbot-turn:{conversation_id}:{message_id}",
        run_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=wait),
    )
    db.commit()


def _merge_fragments(fragments: list[str]) -> str:
    # Preserve field labels and customer wording without another model round trip.
    return "\n".join(fragments)


def dispatch_chatbot_turn(db: Session, *, business_id: int, payload: dict, platform_db: Session | None = None) -> bool:
    conversation_id = int(payload["conversation_id"])
    message_id = int(payload["message_id"])
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id, Conversation.business_id == business_id
    ).first()
    if conversation is None or conversation.bot_mode == "human":
        return False
    source = db.query(Message).filter(
        Message.id == message_id,
        Message.conversation_id == conversation_id,
        Message.direction == "inbound",
    ).first()
    source_has_image = (
        source is not None
        and (source.media_type == "image" or any(item.media_type == "image" for item in source.attachments))
    )
    if source is None or (not (source.content or "").strip() and not source_has_image):
        return False

    turn_started = perf_counter()
    shortcut_match = SHORTCUT_COMMAND.fullmatch((source.content or "").strip()) if not source_has_image else None
    shortcut = shortcut_match.group(1).casefold() if shortcut_match else None

    wait = timedelta(seconds=max(1, min(int(settings.CONVERSATION_TURN_WAIT_SECONDS), 30)))
    source_time = source.received_at or datetime.now(timezone.utc).replace(tzinfo=None)
    queue_wait_ms=max(0,(datetime.now(timezone.utc).replace(tzinfo=None)-source_time).total_seconds()*1000)
    later_fragment = db.query(Message.id).filter(
        Message.conversation_id == conversation_id,
        Message.id > message_id,
        Message.direction == "inbound",
    ).order_by(Message.id.asc()).first()
    if later_fragment is not None and shortcut is None:
        return False

    batch = [source]
    if shortcut is None:
        previous = db.query(Message).filter(
            Message.conversation_id == conversation_id,
            Message.id < message_id,
        ).order_by(Message.id.desc()).limit(12).all()
        # ponytail: cap each turn at 12 fragments; raise only if measured channel traffic needs it.
        for row in previous:
            if not (row.content or "").strip() and not (row.media_type == "image" or any(item.media_type == "image" for item in row.attachments)):
                break
            if (row.received_at is None or batch[0].received_at is None
                    or any((item.raw_payload or {}).get("timestamp_accuracy") == "unavailable_from_source"
                           for item in (row, batch[0]))):
                # Meta history without a source timestamp must not appear adjacent to a live question.
                break
            if SHORTCUT_COMMAND.fullmatch((row.content or "").strip()):
                break
            if row.direction != "inbound":
                break
            gap = (batch[0].received_at or source_time) - (row.received_at or source_time)
            image_followup = (row.media_type == "image" or any(item.media_type == "image" for item in row.attachments)) and any(
                word in (source.content or "").casefold() for word in ("ảnh", "hình", "image", "photo", "picture")
            )
            if not timedelta(0) <= gap <= (max(wait, timedelta(seconds=15)) if image_followup else wait):
                break
            batch.insert(0, row)
            if len(batch) >= 12:
                break
    image_source = next((row for row in reversed(batch) if row.media_type == "image" or any(item.media_type == "image" for item in row.attachments)), None)
    source_has_image = image_source is not None
    fragments = [row.content.strip() for row in batch if row.content and row.content.strip()]
    query = _merge_fragments(fragments) if fragments else ""
    if source_has_image:
        image_context = "Khách gửi ảnh đính kèm. Hãy xem ảnh khi trả lời; nếu chưa có câu hỏi rõ, hỏi một câu làm rõ."
        query = f"{query}\n\n{image_context}".strip()
    if fragments and not source_has_image and shortcut is None:
        from app.models.crm_job import CrmJob
        from app.services.customer_collection_flow import CollectionFlowResult, advance_customer_collection
        from app.services.auto_reply_service import send_text_reply

        # Keep the collection result on the durable turn job before sending.
        # A temporary bridge failure can then retry delivery without adding
        # the same quantity to the quote a second time.
        reply_metadata = payload.get("collection_metadata")
        reply_text = payload.get("collection_reply")
        result = None
        if reply_text is None:
            from app.services.chatbot_agent import deterministic_transaction_safety_reply
            safety_reply = deterministic_transaction_safety_reply(query)
            if safety_reply:
                result = CollectionFlowResult(session_id=0,status="safety",current_field=None,prompt=safety_reply)
            if settings.CHATBOT_GRAPH_ENABLED:
                from app.services.auto_reply_service import get_auto_reply_enabled
                if not get_auto_reply_enabled(db, business_id):
                    return False
                from app.services.privacy_service import customer_memory_opt_out_reply
                privacy = customer_memory_opt_out_reply(db, business_id, conversation.customer_id, query)
                if privacy:
                    result = CollectionFlowResult(session_id=0,status="privacy",current_field=None,prompt=privacy)
            if result is None and not settings.CHATBOT_GRAPH_ENABLED:
                from app.services.customer_order_service import customer_context_reply
                contextual_reply = customer_context_reply(db, business_id, conversation_id, query)
                if contextual_reply:
                    result = CollectionFlowResult(session_id=0,status="customer_context",current_field=None,prompt=contextual_reply)
            if result is None and settings.CHATBOT_GRAPH_ENABLED:
                from app.services.recommendation_interaction_service import record_explicit_chat_recommendation_decline
                record_explicit_chat_recommendation_decline(db,business_id=business_id,conversation_id=conversation_id,text=query,source_message_id=message_id)
                from app.services.conversation_graph import graph_reply
                from app.services.quota_service import QuotaExceededError
                try:
                    result = graph_reply(db,business_id=business_id,conversation=conversation,
                        query=query,job_key=f"{conversation_id}:{message_id}",platform_db=platform_db)
                except QuotaExceededError:
                    raise
                except Exception as error:
                    logger.warning("Conversation graph unavailable: %s",type(error).__name__)
                    from app.services.customer_collection_flow import CollectionFlowResult
                    result = CollectionFlowResult(session_id=0,status="graph_unavailable",current_field=None,
                        prompt="Mình đang gặp lỗi khi kiểm tra dữ liệu nên chưa thể trả lời chắc chắn. Bạn thử lại hoặc nhờ nhân viên hỗ trợ nhé.")
            if result is None:
                result = advance_customer_collection(
                    db=db,
                    business_id=business_id,
                    customer_id=conversation.customer_id,
                    conversation_id=conversation_id,
                    source_channel=conversation.channel,
                    text=query,
                    form_fragments=fragments,
                )
            if result is not None:
                reply_metadata = getattr(result,"metadata",None)
                reply_text = str(result.prompt or "")
                if not reply_text.strip():
                    # Partial checkout fields were saved on the session. Wait
                    # for the customer's remaining entries instead of asking
                    # for the entire form again or routing the values to RAG.
                    return True
                job = db.query(CrmJob).filter(
                    CrmJob.business_id == business_id,
                    CrmJob.idempotency_key == f"chatbot-turn:{conversation_id}:{message_id}",
                ).first()
                if job is not None:
                    job.payload = {**(job.payload or {}), "collection_reply": reply_text, "collection_metadata":reply_metadata}
                    db.commit()
        if reply_text is not None:
            newer = db.query(Message.id).filter(Message.conversation_id == conversation_id,
                Message.direction == "inbound", Message.id > message_id).first()
            if newer is not None:
                return False
            processing_ms = round((perf_counter() - turn_started) * 1000, 1)
            delivery_started = perf_counter()
            delivery_state = "sent"
            try:
                send_text_reply(
                    db=db, conversation_id=conversation_id, channel=conversation.channel,
                    text=reply_text, business_id=business_id,
                    **({"extra_metadata":reply_metadata} if reply_metadata else {}),
                    auto_reply_key=f"turn:{business_id}:{conversation_id}:{batch[0].id}:{message_id}",
                )
            except HTTPException as exc:
                if exc.status_code != 409 or not isinstance(exc.detail, dict) or exc.detail.get("code") != "delivery_unknown":
                    raise
                delivery_state = "unknown"
                logger.warning("Provider delivery unconfirmed for conversation %s; check channel before resending", conversation_id)
            logger.info(
                "Chatbot turn business_id=%s conversation_id=%s message_id=%s correlation_id=%s channel=%s intent=%s delivery_state=%s total_ms=%s queue_wait_ms=%s processing_ms=%s delivery_ms=%s",
                business_id, conversation_id, message_id, f"chatbot-turn:{business_id}:{conversation_id}:{message_id}",
                conversation.channel, getattr(result,"status","unknown"), delivery_state,
                round((datetime.now(timezone.utc).replace(tzinfo=None) - source_time).total_seconds() * 1000, 1),
                round(queue_wait_ms,1),
                processing_ms, round((perf_counter() - delivery_started) * 1000, 1),
            )
            return True
    from app.services.auto_reply_service import process_rag_auto_reply

    return process_rag_auto_reply(
        db=db,
        conversation_id=conversation_id,
        channel=conversation.channel,
        query_text=query[:4000],
        business_id=business_id,
        auto_reply_key=f"turn:{business_id}:{conversation_id}:{batch[0].id}:{message_id}",
        platform_db=platform_db,
        expected_latest_inbound_id=message_id,
        image_message_id=image_source.id if image_source else None,
    )
