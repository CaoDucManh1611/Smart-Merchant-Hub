from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.bases import TenantBase
from app.models.channel import Channel
from app.models.channel_outbound_attempt import ChannelOutboundAttempt
from app.services.channel_delivery import (
    claim_outbound_attempt,
    mark_outbound_attempt_failed,
    mark_outbound_attempt_sent,
)
from app.services.meta_errors import MetaAPIError


def _session() -> Session:
    engine = create_engine("sqlite://")
    Channel.__table__.create(engine)
    ChannelOutboundAttempt.__table__.create(engine)
    session = Session(engine)
    session.add(
        Channel(
            id=5,
            business_id=12,
            channel_type="telegram",
            name="test",
            external_account_id="test-account",
            status="active",
        )
    )
    session.commit()
    return session


def test_delivery_key_replays_sent_message_without_reclaiming() -> None:
    db = _session()
    state, attempt = claim_outbound_attempt(
        db, channel_id=5, business_id=12, conversation_id=21, client_id="client-1-text"
    )
    assert state == "claimed"
    mark_outbound_attempt_sent(db, attempt.id, message_id=101)

    state, replay = claim_outbound_attempt(
        db, channel_id=5, business_id=12, conversation_id=21, client_id="client-1-text"
    )
    assert state == "sent"
    assert replay.message_id == 101
    assert db.query(ChannelOutboundAttempt).count() == 1
    db.close()


def test_only_known_not_delivered_events_can_be_retried() -> None:
    db = _session()
    _, throttled = claim_outbound_attempt(
        db, channel_id=5, business_id=12, conversation_id=21, client_id="client-2-text"
    )
    mark_outbound_attempt_failed(db, throttled.id, MetaAPIError(channel="telegram", stage="send", meta_status=429))
    state, retry = claim_outbound_attempt(
        db, channel_id=5, business_id=12, conversation_id=21, client_id="client-2-text"
    )
    assert state == "claimed"
    assert retry.status == "processing"

    _, uncertain = claim_outbound_attempt(
        db, channel_id=5, business_id=12, conversation_id=21, client_id="client-3-text"
    )
    mark_outbound_attempt_failed(db, uncertain.id, TimeoutError("provider response timed out"))
    state, blocked = claim_outbound_attempt(
        db, channel_id=5, business_id=12, conversation_id=21, client_id="client-3-text"
    )
    assert state == "unknown"
    assert blocked.status == "unknown"
    db.close()


def test_idempotency_key_cannot_be_reused_for_another_conversation() -> None:
    db = _session()
    claim_outbound_attempt(
        db, channel_id=5, business_id=12, conversation_id=21, client_id="client-4-text"
    )
    state, _ = claim_outbound_attempt(
        db, channel_id=5, business_id=12, conversation_id=22, client_id="client-4-text"
    )
    assert state == "key_conflict"
    db.close()
