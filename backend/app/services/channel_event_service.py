"""Tenant-safe inbox persistence for normalized channel events."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from app.contracts.channel_event import NormalizedChannelEvent, bind_event_to_channel
from app.models.channel import Channel, ChannelEvent


def ingest_normalized_events(
    db: Session,
    events: list[NormalizedChannelEvent],
) -> list[NormalizedChannelEvent]:
    """Resolve each external account to its Channel and persist new inbox rows.

    The provider payload is never allowed to select ``business_id``. Unknown
    accounts are ignored so callers can return a safe 404 in webhook paths.
    """

    accepted: list[NormalizedChannelEvent] = []
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

            duplicate = (
                db.query(ChannelEvent.id)
                .filter(
                    ChannelEvent.channel_id == channel.id,
                    ChannelEvent.external_event_id == event.external_event_id,
                )
                .first()
            )
            if duplicate is not None:
                continue

            bound = bind_event_to_channel(event, channel_id=channel.id, business_id=channel.business_id)
            db.add(ChannelEvent(channel_id=channel.id, event_type=event.event_type, external_event_id=event.external_event_id, payload=event.raw_payload, status="received", received_at=datetime.now(UTC).replace(tzinfo=None)))
            accepted.append(bound)
    except OperationalError:
        # Pre-migration development databases still use the legacy path.
        db.rollback()
        return []

    if accepted:
        db.commit()
    return accepted
