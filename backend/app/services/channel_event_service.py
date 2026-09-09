"""Tenant-safe inbox persistence for normalized channel events."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, OperationalError

from app.contracts.channel_event import NormalizedChannelEvent, bind_event_to_channel
from app.core.logging import redact_secrets
from app.models.channel import Channel, ChannelEvent


_RETRYABLE_EVENT_STATUSES = {"failed", "received"}


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def ingest_normalized_events(
    db: Session,
    events: list[NormalizedChannelEvent],
) -> list[NormalizedChannelEvent]:
    """Resolve each external account to its Channel and persist new inbox rows.

    The provider payload is never allowed to select ``business_id``. Unknown
    accounts are ignored so callers can return a safe 404 in webhook paths.
    """

    accepted: list[NormalizedChannelEvent] = []
    changed = False
    try:
        for event in events:
            channel = (
                db.query(Channel)
                .filter(
                    Channel.channel_type == event.provider.value,
                    Channel.external_account_id == event.external_account_id,
                    Channel.status == "active",
                )
                .first()
            )
            if channel is None:
                continue

            existing = (
                db.query(ChannelEvent)
                .filter(
                    ChannelEvent.channel_id == channel.id,
                    ChannelEvent.external_event_id == event.external_event_id,
                )
                .first()
            )
            if existing is not None:
                # A previous delivery may have reached the database but
                # failed before the CRM message was saved.  Only those failed
                # (or legacy ``received``) events are safe to process again;
                # completed and in-flight events remain idempotent.
                if existing.status not in _RETRYABLE_EVENT_STATUSES:
                    continue
                existing.status = "processing"
                existing.error_message = None
                existing.processed_at = None
                accepted.append(
                    bind_event_to_channel(
                        event,
                        channel_id=channel.id,
                        business_id=channel.business_id,
                    )
                )
                changed = True
                continue

            bound = bind_event_to_channel(event, channel_id=channel.id, business_id=channel.business_id)
            record = ChannelEvent(
                channel_id=channel.id,
                event_type=event.event_type,
                external_event_id=event.external_event_id,
                payload=event.raw_payload,
                status="processing",
                received_at=_utcnow(),
            )
            try:
                # A savepoint keeps earlier accepted events intact when two
                # webhook workers race to record the same provider delivery.
                with db.begin_nested():
                    db.add(record)
                    db.flush()
            except IntegrityError:
                # Another worker won the unique (channel, external-event)
                # insert.  It owns the in-flight work, so never duplicate it.
                continue
            accepted.append(bound)
            changed = True
    except OperationalError:
        # Pre-migration development databases still use the legacy path.
        db.rollback()
        return []

    if changed:
        db.commit()
    return accepted


def mark_channel_event_processed(db: Session, event: NormalizedChannelEvent) -> None:
    """Finish one normalized delivery after all of its messages are stored."""
    if event.channel_id is None:
        raise ValueError("A channel-bound event is required")
    db.query(ChannelEvent).filter(
        ChannelEvent.channel_id == event.channel_id,
        ChannelEvent.external_event_id == event.external_event_id,
    ).update(
        {
            ChannelEvent.status: "processed",
            ChannelEvent.error_message: None,
            ChannelEvent.processed_at: _utcnow(),
        },
        synchronize_session=False,
    )
    db.commit()


def mark_channel_event_failed(
    db: Session,
    event: NormalizedChannelEvent,
    error: Exception | str,
) -> None:
    """Keep a redacted, retryable failure state for a provider delivery."""
    if event.channel_id is None:
        return
    # Never persist a full provider payload or request headers in an error
    # field.  They can contain customer content or credentials.
    reason = redact_secrets(" ".join(str(error).split()))[:500] or type(error).__name__
    db.query(ChannelEvent).filter(
        ChannelEvent.channel_id == event.channel_id,
        ChannelEvent.external_event_id == event.external_event_id,
    ).update(
        {
            ChannelEvent.status: "failed",
            ChannelEvent.error_message: reason,
            ChannelEvent.processed_at: None,
        },
        synchronize_session=False,
    )
    db.commit()
