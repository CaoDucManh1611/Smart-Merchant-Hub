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
    plain = "\n".join(fragments)
    if len(fragments) == 1 or not settings.conversation_gemini_api_keys:
        return plain
    try:
        from app.rag.llm_caller import call_gemini_for_turn

        combined = call_gemini_for_turn(fragments)
        # A failed or over-creative interpretation must never replace the
        # customer's original words with an invented product or order fact.
        original_numbers = set(re.findall(r"\d+(?:[.,]\d+)*", plain))
        combined_numbers = set(re.findall(r"\d+(?:[.,]\d+)*", combined or ""))
        color_terms = ("hồng", "hong", "pink", "đỏ", "do", "red", "xanh", "blue", "green", "đen", "den", "black", "trắng", "trang", "white", "vàng", "vang", "yellow", "tím", "tim", "purple", "nâu", "nau", "brown")
        original_lower, combined_lower = plain.casefold(), (combined or "").casefold()
        colors_preserved = all(term not in original_lower or term in combined_lower for term in color_terms)
        sizes_preserved = all(
            value.casefold() in combined_lower
            for value in re.findall(r"\b(?:size|sz)\s*[a-z0-9-]+", plain, flags=re.IGNORECASE)
        )
        if (combined and original_numbers == combined_numbers and colors_preserved and sizes_preserved
                and len(combined) <= min(4000, len(plain) * 2 + 80)):
            return combined
    except Exception:
        logger.warning("Gemini turn interpretation unavailable; retaining original fragments")
    return plain


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
    if source is None or not source.content or not source.content.strip():
        return False

    turn_started = perf_counter()

    wait = timedelta(seconds=max(1, min(int(settings.CONVERSATION_TURN_WAIT_SECONDS), 30)))
    source_time = source.received_at or datetime.now(timezone.utc).replace(tzinfo=None)
    later_fragment = db.query(Message.id).filter(
        Message.conversation_id == conversation_id,
        Message.id > message_id,
        Message.direction == "inbound",
        Message.received_at <= source_time + wait,
        Message.received_at >= source_time,
    ).order_by(Message.id.asc()).first()
    if later_fragment is not None:
        return False

    batch = [source]
    previous = db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.id < message_id,
    ).order_by(Message.id.desc()).limit(12).all()
    # ponytail: cap each turn at 12 fragments; raise only if measured channel traffic needs it.
    for row in previous:
        if row.direction != "inbound" or not row.content or not row.content.strip():
            break
        gap = (batch[0].received_at or source_time) - (row.received_at or source_time)
        if not timedelta(0) <= gap <= wait:
            break
        batch.insert(0, row)
        if len(batch) >= 12:
            break
    fragments = [row.content.strip() for row in batch]
    query = _merge_fragments(fragments)
    if conversation.channel in {"shopee", "tiktok"}:
        from app.models.crm_job import CrmJob
        from app.services.customer_collection_flow import advance_customer_collection
        from app.services.auto_reply_service import send_text_reply

        # Keep the collection result on the durable turn job before sending.
        # A temporary bridge failure can then retry delivery without adding
        # the same quantity to the quote a second time.
        reply_text = payload.get("collection_reply")
        if reply_text is None:
            result = advance_customer_collection(
                db=db,
                business_id=business_id,
                customer_id=conversation.customer_id,
                conversation_id=conversation_id,
                source_channel=conversation.channel,
                text=query,
            )
            if result is not None:
                reply_text = result.prompt
                job = db.query(CrmJob).filter(
                    CrmJob.business_id == business_id,
                    CrmJob.idempotency_key == f"chatbot-turn:{conversation_id}:{message_id}",
                ).first()
                if job is not None:
                    job.payload = {**(job.payload or {}), "collection_reply": reply_text}
                    db.commit()
        if reply_text is not None:
            processing_ms = round((perf_counter() - turn_started) * 1000, 1)
            delivery_started = perf_counter()
            try:
                send_text_reply(
                    db=db, conversation_id=conversation_id, channel=conversation.channel,
                    text=reply_text, business_id=business_id,
                    auto_reply_key=f"turn:{business_id}:{conversation_id}:{batch[0].id}:{message_id}",
                )
            except HTTPException as exc:
                if exc.status_code != 409 or not isinstance(exc.detail, dict) or exc.detail.get("code") != "delivery_unknown":
                    raise
                logger.warning("Shopee delivery unconfirmed for conversation %s; check channel before resending", conversation_id)
            logger.info(
                "Chatbot turn channel=%s conversation=%s wait_ms=%s processing_ms=%s delivery_ms=%s",
                conversation.channel, conversation_id,
                round((datetime.now(timezone.utc).replace(tzinfo=None) - source_time).total_seconds() * 1000, 1),
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
    )
