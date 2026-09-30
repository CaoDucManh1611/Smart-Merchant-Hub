"""Safe idempotency for provider sends with ambiguous delivery results."""

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.channel_outbound_attempt import ChannelOutboundAttempt
from app.services.channel_retry import is_retryable_provider_error
from app.services.meta_errors import MetaAPIError


_SAFE_PROVIDER_REJECTIONS = {400, 401, 403, 404, 413, 415, 422}


def validate_client_id(value: str | None) -> str:
    client_id = str(value or "").strip()
    if (
        not 8 <= len(client_id) <= 160
        or any(not (char.isalnum() or char in "-_.:") for char in client_id)
    ):
        raise HTTPException(status_code=422, detail="client_id is required and must be a valid message key")
    return client_id


def claim_outbound_attempt(
    db: Session,
    *,
    channel_id: int | None,
    business_id: int,
    conversation_id: int,
    client_id: str,
) -> tuple[str, ChannelOutboundAttempt]:
    query = select(ChannelOutboundAttempt).where(
        ChannelOutboundAttempt.business_id == business_id,
        ChannelOutboundAttempt.client_id == client_id,
    )
    attempt = db.scalar(query)
    if attempt is None:
        attempt = ChannelOutboundAttempt(
            channel_id=channel_id,
            business_id=business_id,
            conversation_id=conversation_id,
            client_id=client_id,
            status="processing",
        )
        db.add(attempt)
        try:
            db.commit()
            return "claimed", attempt
        except IntegrityError:
            db.rollback()
            attempt = db.scalar(query)
            if attempt is None:
                raise
    if attempt.business_id != business_id or attempt.conversation_id != conversation_id:
        return "key_conflict", attempt
    if attempt.status == "retryable_failed":
        claimed = db.execute(
            update(ChannelOutboundAttempt)
            .where(
                ChannelOutboundAttempt.id == attempt.id,
                ChannelOutboundAttempt.status == "retryable_failed",
            )
            .values(status="processing", error_code=None, updated_at=func.now())
        )
        db.commit()
        attempt = db.get(ChannelOutboundAttempt, attempt.id)
        if claimed.rowcount == 1:
            return "claimed", attempt
    return attempt.status, attempt


def mark_outbound_attempt_sent(db: Session, attempt_id: int, *, message_id: int | None) -> None:
    db.execute(
        update(ChannelOutboundAttempt)
        .where(ChannelOutboundAttempt.id == attempt_id, ChannelOutboundAttempt.status == "processing")
        .values(status="sent", error_code=None, message_id=message_id, updated_at=func.now())
    )
    db.commit()


def mark_outbound_attempt_failed(db: Session, attempt_id: int, error: Exception) -> None:
    status = "unknown"
    error_code = "delivery_unknown"
    if is_retryable_provider_error(error):
        status, error_code = "retryable_failed", "provider_retryable"
    elif isinstance(error, MetaAPIError) and error.meta_status in _SAFE_PROVIDER_REJECTIONS:
        status, error_code = "retryable_failed", "provider_rejected"
    elif isinstance(error, HTTPException) and 400 <= error.status_code < 500 and error.status_code not in {408, 409}:
        status, error_code = "retryable_failed", "request_rejected"
    db.execute(
        update(ChannelOutboundAttempt)
        .where(ChannelOutboundAttempt.id == attempt_id, ChannelOutboundAttempt.status == "processing")
        .values(status=status, error_code=error_code, updated_at=func.now())
    )
    db.commit()
