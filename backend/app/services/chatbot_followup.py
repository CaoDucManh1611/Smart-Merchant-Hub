"""Scheduling and delivery for proactive customer care messages."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.chatbot_followup import ChatbotFollowUp
from app.models.conversation import Conversation


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _key(business_id: int, conversation_id: int, kind: str, run_at: datetime, message: str) -> str:
    raw = f"{business_id}:{conversation_id}:{kind}:{run_at.isoformat()}:{message}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def schedule_followup(
    db: Session,
    business_id: int,
    conversation_id: int,
    message: str,
    run_at: datetime,
    *,
    kind: str = "custom",
    metadata: dict | None = None,
) -> ChatbotFollowUp:
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.business_id == business_id,
    ).first()
    if conversation is None:
        raise ValueError("conversation_not_found")
    message = str(message or "").strip()
    if not message:
        raise ValueError("message_required")
    if run_at.tzinfo is not None:
        run_at = run_at.astimezone(timezone.utc).replace(tzinfo=None)
    key = _key(business_id, conversation_id, kind, run_at, message)
    existing = db.query(ChatbotFollowUp).filter(
        ChatbotFollowUp.business_id == business_id,
        ChatbotFollowUp.idempotency_key == key,
    ).first()
    if existing is not None:
        return existing
    row = ChatbotFollowUp(
        business_id=business_id,
        conversation_id=conversation_id,
        customer_id=conversation.customer_id,
        kind=kind,
        message=message,
        run_at=run_at,
        idempotency_key=key,
        metadata_=metadata or {},
    )
    db.add(row)
    db.flush()
    # Reuse the existing durable CRM job worker; the API endpoint remains
    # available for development and manual replay.
    from app.services.job_service import enqueue_job

    enqueue_job(
        db,
        business_id=business_id,
        kind="chatbot.followup",
        payload={"followup_id": row.id},
        idempotency_key=f"chatbot-followup:{key}",
        run_at=run_at,
    )
    return row


def _send_followup(db: Session, row: ChatbotFollowUp) -> dict:
    from app.services.auto_reply_service import (
        _get_conversation_recipient,
        _save_auto_reply_outbound,
        _send_channel_reply,
    )

    conversation = db.query(Conversation).filter(
        Conversation.id == row.conversation_id,
        Conversation.business_id == row.business_id,
    ).first()
    if conversation is None:
        raise ValueError("conversation_not_found")
    if conversation.bot_mode == "human":
        raise ValueError("human_takeover")
    channel, recipient_id = _get_conversation_recipient(db, row.conversation_id, row.business_id)
    response = _send_channel_reply(
        db=db,
        conversation_id=row.conversation_id,
        channel=channel,
        recipient_id=recipient_id,
        text=row.message,
        business_id=row.business_id,
    )
    _save_auto_reply_outbound(
        db=db,
        conversation_id=row.conversation_id,
        channel=channel,
        recipient_id=recipient_id,
        external_message_id=response.get("message_id"),
        content=row.message,
        meta_response=response,
        source_document_ids=[],
    )
    return response


def dispatch_due_followups(db: Session, business_id: int, *, limit: int = 50, now: datetime | None = None, followup_id: int | None = None) -> dict:
    current = now or _now()
    rows = db.query(ChatbotFollowUp).filter(
        ChatbotFollowUp.business_id == business_id,
        ChatbotFollowUp.status == "scheduled",
        ChatbotFollowUp.run_at <= current,
    )
    if followup_id is not None:
        rows = rows.filter(ChatbotFollowUp.id == followup_id)
    rows = rows.order_by(ChatbotFollowUp.run_at.asc(), ChatbotFollowUp.id.asc()).limit(limit).all()
    sent = 0
    failed = 0
    skipped = 0
    for row in rows:
        row.attempts = int(row.attempts or 0) + 1
        try:
            _send_followup(db, row)
            row.status = "sent"
            row.sent_at = current
            row.last_error = None
            sent += 1
        except ValueError as exc:
            if str(exc) == "human_takeover":
                row.status = "cancelled"
                skipped += 1
            else:
                row.status = "failed" if row.attempts >= 3 else "scheduled"
                row.last_error = str(exc)
                failed += 1
        except Exception as exc:
            row.status = "failed" if row.attempts >= 3 else "scheduled"
            row.last_error = str(exc)[:500]
            failed += 1
    db.commit()
    return {"sent": sent, "failed": failed, "skipped": skipped, "total": len(rows)}
