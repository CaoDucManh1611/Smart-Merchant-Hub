"""Tenant-safe inbox persistence for normalized channel events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, OperationalError

from app.contracts.channel_event import NormalizedChannelEvent, bind_event_to_channel
from app.integrations import get_channel_adapter
from app.models.channel import Channel, ChannelEvent


_RETRYABLE_EVENT_STATUSES = {"failed", "received"}
_PROCESSING_LEASE = timedelta(minutes=5)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def normalize_stored_channel_event(
    channel: Channel,
    stored_event: ChannelEvent,
) -> NormalizedChannelEvent:
    """Re-parse a failed inbox event and verify its stable provider identity."""
    provider = str(channel.channel_type or "").strip().lower()
    if provider not in {"facebook", "instagram", "telegram", "zalo"}:
        raise ValueError("Channel provider does not support inbox replay")
    payload = stored_event.payload
    if not isinstance(payload, dict):
        raise ValueError("Stored provider payload is invalid")

    adapter = get_channel_adapter(provider)
    if provider in {"facebook", "instagram"}:
        # Meta event rows retain the individual messaging event, not the full
        # webhook envelope; rebuild only the minimum account wrapper required
        # by the existing adapter.
        events = adapter.parse_events({
            "entry": [{
                "id": channel.external_account_id,
                "messaging": [payload],
            }]
        })
    else:
        events = adapter.parse_events(
            payload,
            external_account_id=channel.external_account_id,
        )

    matching = [
        event
        for event in events
        if event.external_event_id == stored_event.external_event_id
    ]
    if len(matching) != 1:
        raise ValueError("Stored payload does not match the failed event identity")
    return bind_event_to_channel(
        matching[0],
        channel_id=int(channel.id),
        business_id=int(channel.business_id),
    )


def ingest_normalized_events(
    db: Session,
    events: list[NormalizedChannelEvent],
) -> list[NormalizedChannelEvent]:
    """Persist inbox rows using a session already routed to the shop schema.

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
            if (
                (event.channel_id is not None and event.channel_id != channel.id)
                or (event.business_id is not None and event.business_id != channel.business_id)
            ):
                raise PermissionError("Channel event does not match the routed shop channel")

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
                # (or legacy ``received``) events are safe to process again.
                # A worker crash can strand ``processing`` forever, so reclaim
                # it after a bounded lease; message IDs remain the final
                # idempotency guard if the old worker was only slow.
                stale_processing = (
                    existing.status == "processing"
                    and (
                        existing.received_at is None
                        or existing.received_at <= _utcnow() - _PROCESSING_LEASE
                    )
                )
                if existing.status not in _RETRYABLE_EVENT_STATUSES and not stale_processing:
                    continue
                claim = db.query(ChannelEvent).filter(
                    ChannelEvent.id == existing.id,
                    ChannelEvent.status == existing.status,
                )
                if stale_processing:
                    claim = claim.filter(
                        ChannelEvent.received_at <= _utcnow() - _PROCESSING_LEASE
                    )
                claimed = claim.update(
                    {
                        ChannelEvent.status: "processing",
                        ChannelEvent.received_at: _utcnow(),
                        ChannelEvent.error_message: None,
                        ChannelEvent.processed_at: None,
                    },
                    synchronize_session=False,
                )
                if claimed != 1:
                    continue
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
        db.rollback()
        raise

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
    # Exception text may include SQL parameters, signed URLs, or provider
    # payload fragments. Persist only a compact diagnostic code, never it.
    if isinstance(error, Exception):
        parts = [type(error).__name__]
        provider = str(getattr(error, "channel", "") or "").lower()
        if provider in {"facebook", "instagram", "telegram", "zalo", "tiktok"}:
            parts.append(provider)
        stage = str(getattr(error, "stage", "") or "").lower()
        if stage and stage.replace("_", "").replace("-", "").isalnum():
            parts.append(stage)
        status = getattr(error, "meta_status", None)
        if isinstance(status, int) and 100 <= status <= 599:
            parts.append(str(status))
        reason = ":".join(parts)[:160]
    else:
        reason = "processing_failed"
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
