import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import connector_pairing

from app.api import local_connectors
from app.api.zalo import _sync_zalo_oa_user_history
from app.core.config import settings
from app.models import Business, Channel, ChannelEvent, Conversation, Customer, Message
from app.services.channel_credentials import encrypt_token
from app.services.message_service import process_and_save_message
from unittest.mock import patch


def test_history_normalizer_preserves_original_time_and_direction():
    inbound = local_connectors._normalize_history_message("tiktok", {
        "threadId": "thread-1", "customerId": "buyer-1", "messageId": "msg-1",
        "direction": "inbound", "message": "hello", "createdAt": 1_770_000_000_000,
    })
    outbound = local_connectors._normalize_history_message("tiktok", {
        "threadId": "thread-1", "customerId": "buyer-1", "messageId": "msg-2",
        "direction": "outbound", "message": "welcome", "createdAt": "2026-02-02T00:00:00+07:00",
    })

    assert inbound["created_at"] == datetime.fromtimestamp(1_770_000_000, tz=timezone.utc).replace(tzinfo=None)
    assert inbound["direction"] == "inbound"
    assert outbound["created_at"] == datetime(2026, 2, 1, 17, 0)
    assert outbound["direction"] == "outbound"


def test_history_endpoint_uses_side_effect_free_persistence_and_counts_duplicates(monkeypatch):
    channel = type("ChannelRow", (), {
        "id": 11, "business_id": 7, "channel_type": "tiktok",
        "status": "active", "external_account_id": "shop-7",
    })()

    class TenantDb:
        @staticmethod
        def get(_model, _channel_id):
            return channel

    @contextmanager
    def tenant_session(_schema):
        yield TenantDb()

    calls = []

    def persist(*, message, history_import, **_kwargs):
        calls.append((message, history_import))
        return {"_created": len(calls) == 1}

    monkeypatch.setattr(local_connectors, "_connector_channel", lambda *_args: (7, 11))
    monkeypatch.setattr(local_connectors, "_tenant_schema", lambda *_args: "tenant_7")
    monkeypatch.setattr(local_connectors, "tenant_session", tenant_session)
    monkeypatch.setattr(local_connectors, "process_and_save_message", persist)

    result = local_connectors.receive_local_connector_history(
        "tiktok",
        {"messages": [
            {"threadId": "thread-1", "customerId": "buyer-1", "messageId": "msg-1", "message": "hello"},
            {"threadId": "thread-1", "customerId": "buyer-1", "messageId": "msg-2", "message": "reply", "direction": "outbound"},
            {"threadId": "", "customerId": "buyer-1", "messageId": "bad", "message": "skip"},
        ]},
        "Bearer connector-token",
        object(),
    )

    assert result == {"status": "received", "imported": 1, "duplicates": 1, "skipped": 1}
    assert all(history_import for _, history_import in calls)
    assert calls[0][0]["external_user_id"] == "buyer-1"
    assert calls[1][0]["direction"] == "outbound"
    assert calls[0][0]["raw_payload"]["history_import"] is True


def test_history_endpoint_rejects_unbounded_batches():
    with pytest.raises(HTTPException) as error:
        local_connectors.receive_local_connector_history(
            "tiktok", {"messages": [{}] * 101}, "Bearer token", object()
        )
    assert error.value.status_code == 422


def test_history_checkpoint_replays_until_a_thread_is_fully_acknowledged(tmp_path):
    path = tmp_path / "history.json"
    checkpoint = connector_pairing.load_history_checkpoint(path)
    checkpoint = connector_pairing.mark_history_thread_complete(path, checkpoint, "thread-1")

    resumed = connector_pairing.load_history_checkpoint(path)
    assert resumed == {"version": 1, "completed_threads": ["thread-1"], "complete": False}
    connector_pairing.mark_history_complete(path)
    assert connector_pairing.load_history_checkpoint(path)["complete"] is True
    assert connector_pairing.history_checkpoint_path(tmp_path, "tiktok", "token-a") != connector_pairing.history_checkpoint_path(tmp_path, "tiktok", "token-b")


def test_history_import_persists_old_direction_and_timestamp_without_automation():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Business.metadata.create_all(engine)
    occurred_at = datetime(2025, 5, 1, 3, 30)
    with Session(engine) as db:
        business = Business(name="History Shop", slug="history-shop")
        db.add(business)
        db.flush()
        channel = Channel(
            business_id=business.id,
            channel_type="tiktok",
            name="TikTok Shop",
            external_account_id="seller-1",
            status="active",
        )
        db.add(channel)
        db.flush()
        message = {
            "channel": "tiktok", "business_id": business.id, "channel_id": channel.id,
            "external_account_id": channel.external_account_id, "external_user_id": "buyer-1",
            "external_message_id": "tiktok:history-1", "direction": "outbound",
            "content": "Shop reply", "received_at": occurred_at,
            "raw_payload": {"threadId": "thread-1", "history_import": True},
        }
        with patch("app.services.message_service.create_notification", side_effect=AssertionError), \
             patch("app.services.conversation_turn_service.schedule_chatbot_turn", side_effect=AssertionError), \
             patch("app.services.workflow_engine.emit_workflow_event", side_effect=AssertionError):
            saved = process_and_save_message(db, message, history_import=True)
            duplicate = process_and_save_message(db, dict(message), history_import=True)

        stored = db.scalar(select(Message).where(Message.external_message_id == "tiktok:history-1"))
        conversation = db.scalar(select(Conversation))
        customer = db.scalar(select(Customer))
        assert stored.direction == "outbound"
        assert stored.sender_type == "staff"
        assert stored.received_at == occurred_at
        assert stored.raw_payload["history_import"] is True
        assert conversation.last_message_at.replace(tzinfo=None) >= occurred_at
        assert customer.external_user_id == "buyer-1"
        assert saved["_created"] is True
        assert duplicate["_created"] is False


def test_zalo_oa_history_resumes_and_records_checkpoint_without_reprocessing_webhook(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Business.metadata.create_all(engine)
    with Session(engine) as db:
        business = Business(name="Zalo History Shop", slug="zalo-history-shop")
        db.add(business)
        db.flush()
        channel = Channel(
            business_id=business.id, channel_type="zalo", name="Zalo OA",
            external_account_id="oa-1", status="active", config={"provider": "zalo_oa"},
            access_token_encrypted=encrypt_token("access-token", settings.CHANNEL_ENCRYPTION_KEY),
        )
        db.add(channel)
        db.commit()
        channel_id, business_id = channel.id, business.id

    @contextmanager
    def tenant_session(_schema):
        with Session(engine) as db:
            yield db

    records = [
        {"message_id": "shop-1", "src": 0, "time": 1_770_000_000_000, "type": "text", "message": "Reply"},
        {"message_id": "buyer-1", "src": 1, "time": 1_770_000_000_001, "type": "text", "message": "Question"},
        {"message_id": "current-event", "src": 1, "time": 1_770_000_000_002, "type": "text", "message": "Live"},
    ]

    class Adapter:
        @staticmethod
        def fetch_conversation_history(**kwargs):
            assert kwargs["count"] == 10
            return records

    imported = []

    def persist(*, message, history_import, **_kwargs):
        imported.append((message, history_import))
        return {"_created": True}

    monkeypatch.setattr("app.api.zalo.tenant_session", tenant_session)
    monkeypatch.setattr("app.api.zalo.get_channel_adapter", lambda _provider: Adapter())
    monkeypatch.setattr("app.api.zalo.process_and_save_message", persist)
    _sync_zalo_oa_user_history(
        "tenant", channel_id, business_id, "user-1", ["zalo:oa-1:current-event"]
    )

    assert [message["external_message_id"] for message, _ in imported] == ["zalo:oa-1:shop-1", "zalo:oa-1:buyer-1"]
    assert all(import_flag for _, import_flag in imported)
    assert [message["direction"] for message, _ in imported] == ["outbound", "inbound"]
    with Session(engine) as db:
        marker = db.scalar(select(ChannelEvent).where(ChannelEvent.external_event_id == "history-sync:zalo:user-1"))
        assert marker.status == "processed"
        assert marker.payload["offset"] == 3
