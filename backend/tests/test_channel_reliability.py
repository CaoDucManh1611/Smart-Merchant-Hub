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
    normalize_stored_channel_event,
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
        assert row.error_message == "RuntimeError"

        class ProviderFailure(Exception):
            channel = "facebook"
            stage = "text_send"
            meta_status = 429

        mark_channel_event_failed(db, first[0], ProviderFailure("customer text and token=private"))
        assert db.query(ChannelEvent).one().error_message == "ProviderFailure:facebook:text_send:429"

        retried = ingest_normalized_events(db, [_event()])
        assert len(retried) == 1
        assert db.query(ChannelEvent).count() == 1
        assert db.query(ChannelEvent).one().status == "processing"

        mark_channel_event_processed(db, retried[0])
        assert ingest_normalized_events(db, [_event()]) == []
        assert db.query(ChannelEvent).one().status == "processed"


def test_stale_processing_event_can_be_reclaimed_after_worker_crash():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        business = Business(name="Channel Recovery", slug="channel-recovery")
        db.add(business)
        db.flush()
        db.add(Channel(
            business_id=business.id,
            channel_type="facebook",
            name="Recovery Page",
            external_account_id="page-reliability-1",
            status="active",
        ))
        db.commit()

        first = ingest_normalized_events(db, [_event("fb-crashed-worker")])
        assert len(first) == 1
        row = db.query(ChannelEvent).one()
        row.received_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=10)
        db.commit()

        recovered = ingest_normalized_events(db, [_event("fb-crashed-worker")])

        assert len(recovered) == 1
        assert db.query(ChannelEvent).count() == 1
        assert db.query(ChannelEvent).one().status == "processing"
        assert db.query(ChannelEvent).one().received_at > datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)


def test_failed_event_payload_reconstructs_one_idempotent_event_for_replay():
    cases = [
        (
            "facebook",
            "page-1",
            "fb-mid-1",
            {"sender": {"id": "customer-1"}, "recipient": {"id": "page-1"}, "message": {"mid": "fb-mid-1", "text": "hello"}},
        ),
        (
            "instagram",
            "ig-account-1",
            "ig-mid-1",
            {"sender": {"id": "customer-1"}, "recipient": {"id": "ig-account-1"}, "message": {"mid": "ig-mid-1", "text": "hello"}},
        ),
        (
            "telegram",
            "bot-1",
            "telegram:9:4",
            {"update_id": 9, "message": {"message_id": 4, "from": {"id": 12}, "chat": {"id": 12}, "text": "hello"}},
        ),
        (
            "zalo",
            "oa-1",
            "zalo:oa-1:z-1",
            {"event_name": "message", "message": {"message_id": "z-1", "from": {"id": "customer-1"}, "chat": {"id": "customer-1"}, "text": "hello"}},
        ),
    ]

    for provider, account_id, event_id, payload in cases:
        channel = Channel(
            id=7,
            business_id=1,
            channel_type=provider,
            name="Test channel",
            external_account_id=account_id,
            status="active",
        )
        stored = ChannelEvent(
            id=11,
            channel_id=7,
            event_type="message",
            external_event_id=event_id,
            payload=payload,
            status="failed",
        )

        normalized = normalize_stored_channel_event(channel, stored)

        assert normalized.external_event_id == event_id
        assert normalized.provider.value == provider
        assert normalized.channel_id == 7
        assert normalized.business_id == 1


def test_failed_event_replay_rejects_payload_that_no_longer_matches_event_identity():
    channel = Channel(
        id=7,
        business_id=1,
        channel_type="facebook",
        name="Test page",
        external_account_id="page-1",
        status="active",
    )
    stored = ChannelEvent(
        id=11,
        channel_id=7,
        event_type="message",
        external_event_id="expected-mid",
        payload={"sender": {"id": "customer-1"}, "message": {"mid": "different-mid", "text": "hello"}},
        status="failed",
    )

    try:
        normalize_stored_channel_event(channel, stored)
    except ValueError as exc:
        assert "event identity" in str(exc)
    else:
        raise AssertionError("A stored payload with a different message ID must not be replayed")


def test_provider_retry_retries_explicit_rate_limit_then_succeeds():
    attempts = 0

    def request() -> dict[str, bool]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise MetaAPIError(channel="facebook", stage="text_send", meta_status=429)
        return {"ok": True}

    result = run_with_provider_retry(
        provider="facebook",
        operation="text_send",
        request=request,
        sleep=lambda _seconds: None,
    )

    assert result == {"ok": True}
    assert attempts == 2


def test_provider_retry_does_not_retry_ambiguous_server_error():
    attempts = 0

    def request() -> dict[str, bool]:
        nonlocal attempts
        attempts += 1
        raise MetaAPIError(channel="facebook", stage="text_send", meta_status=503)

    try:
        run_with_provider_retry(
            provider="facebook",
            operation="text_send",
            request=request,
            sleep=lambda _seconds: None,
        )
    except MetaAPIError:
        pass
    else:
        raise AssertionError("Ambiguous 5xx must surface rather than risk a duplicate send")
    assert attempts == 1


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
