"""Reliability regression tests for the four-channel Unified Inbox."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.contracts.channel_event import NormalizedChannelEvent
from app.database.session import Base
from app.models.business import Business
from app.models.channel import Channel, ChannelEvent
from app.services.channel_event_service import (
    ingest_normalized_events,
    mark_channel_event_failed,
    mark_channel_event_processed,
)
from app.services.channel_retry import run_with_provider_retry
from app.services.channel_service import channel_credential_status
from app.services.meta_errors import MetaAPIError


def _event(event_id: str = "fb-reliability-1") -> NormalizedChannelEvent:
    return NormalizedChannelEvent(
        provider="facebook",
        external_event_id=event_id,
        event_type="message",
        external_account_id="page-reliability-1",
        raw_payload={"message": {"mid": event_id}},
    )


def test_failed_inbound_event_can_retry_without_creating_another_event_row():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        business = Business(name="Channel Reliability", slug="channel-reliability")
        db.add(business)
        db.flush()
        db.add(
            Channel(
                business_id=business.id,
                channel_type="facebook",
                name="Reliability Page",
                external_account_id="page-reliability-1",
                status="active",
            )
        )
        db.commit()

        first = ingest_normalized_events(db, [_event()])
        assert len(first) == 1
        row = db.query(ChannelEvent).one()
        assert row.status == "processing"

        mark_channel_event_failed(db, first[0], RuntimeError("access_token=must-not-be-stored"))
        row = db.query(ChannelEvent).one()
        assert row.status == "failed"
        assert "must-not-be-stored" not in (row.error_message or "")
        assert "[REDACTED]" in (row.error_message or "")

        retried = ingest_normalized_events(db, [_event()])
        assert len(retried) == 1
        assert db.query(ChannelEvent).count() == 1
        assert db.query(ChannelEvent).one().status == "processing"

        mark_channel_event_processed(db, retried[0])
        assert ingest_normalized_events(db, [_event()]) == []
        assert db.query(ChannelEvent).one().status == "processed"


def test_provider_retry_retries_explicit_meta_503_then_succeeds():
    attempts = 0

    def request() -> dict[str, bool]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise MetaAPIError(channel="facebook", stage="text_send", meta_status=503)
        return {"ok": True}

    result = run_with_provider_retry(
        provider="facebook",
        operation="text_send",
        request=request,
        sleep=lambda _seconds: None,
    )

    assert result == {"ok": True}
    assert attempts == 2


def test_provider_retry_never_retries_ambiguous_read_timeout():
    attempts = 0
    request = httpx.Request("POST", "https://provider.example/messages")

    def send() -> None:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("delivery outcome unknown", request=request)

    try:
        run_with_provider_retry(
            provider="telegram",
            operation="text_send",
            request=send,
            sleep=lambda _seconds: None,
        )
    except httpx.ReadTimeout:
        pass
    else:
        raise AssertionError("Read timeout must be surfaced to avoid a duplicate send")
    assert attempts == 1


def test_channel_credential_status_detects_expired_and_expiring_tokens():
    channel = Channel(
        business_id=1,
        channel_type="facebook",
        name="Page",
        external_account_id="page-1",
        access_token_encrypted="encrypted",
        config={"token_expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat()},
    )
    assert channel_credential_status(channel)["state"] == "expired"

    channel.config = {"token_expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()}
    assert channel_credential_status(channel)["state"] == "expiring"
