import asyncio
import io
import json
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


def test_configure_local_connector_accepts_pairing_code_at_saved_connection_prompt(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    package_dir = tmp_path / "package"
    runtime_dir.mkdir()
    old_token = "CONN.facebook.4.5.oldTokenValue1234"
    pairing_code = "PAIR.facebook.4.5.TestPairingValue1234"
    (runtime_dir / "facebook_connector_config.json").write_text(json.dumps({
        "backend_url": "http://127.0.0.1:8000",
        "connector_token": old_token,
    }), encoding="utf-8")
    monkeypatch.delenv("SMART_MERCHANT_AUTO_RESTART", raising=False)
    monkeypatch.setattr("builtins.input", lambda _prompt: pairing_code)
    request_bodies = []

    def fake_urlopen(request, timeout):
        assert timeout == 20
        request_bodies.append(json.loads(request.data.decode("utf-8")))
        return io.BytesIO(json.dumps({
            "channel_type": "facebook",
            "connector_token": "CONN.facebook.4.5.newTokenValue1234",
        }).encode("utf-8"))

    monkeypatch.setattr(connector_pairing, "urlopen", fake_urlopen)
    monkeypatch.setattr(connector_pairing, "start_connector_heartbeat", lambda *_args: None)

    backend_url, connector_token = connector_pairing.configure_local_connector(
        "facebook", runtime_dir, package_dir, config_filename="facebook_connector_config.json"
    )

    assert backend_url == "http://127.0.0.1:8000"
    assert connector_token == "CONN.facebook.4.5.newTokenValue1234"
    assert request_bodies == [{"pairing_code": pairing_code}]
    saved = json.loads((runtime_dir / "facebook_connector_config.json").read_text(encoding="utf-8"))
    assert saved["connector_token"] == connector_token


def test_configure_local_connector_rejects_bad_choice_instead_of_reusing_stale_token(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime"
    package_dir = tmp_path / "package"
    runtime_dir.mkdir()
    (runtime_dir / "facebook_connector_config.json").write_text(json.dumps({
        "backend_url": "http://127.0.0.1:8000",
        "connector_token": "CONN.facebook.4.5.oldTokenValue1234",
    }), encoding="utf-8")
    monkeypatch.delenv("SMART_MERCHANT_AUTO_RESTART", raising=False)
    monkeypatch.setattr("builtins.input", lambda _prompt: "not-a-pairing-code")
    monkeypatch.setattr(
        connector_pairing,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("must not send an invalid pairing choice"),
    )

    with pytest.raises(SystemExit, match="Lựa chọn không hợp lệ"):
        connector_pairing.configure_local_connector(
            "facebook", runtime_dir, package_dir, config_filename="facebook_connector_config.json"
        )


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


def test_duplicate_meta_history_refreshes_corrected_message_timestamp(monkeypatch):
    channel = type("ChannelRow", (), {
        "id": 11, "business_id": 7, "channel_type": "instagram",
        "status": "active", "external_account_id": "instagram-shop-7",
    })()

    class TenantDb:
        def __init__(self):
            self.updates = []

        @staticmethod
        def get(_model, _channel_id):
            return channel

        def execute(self, statement, params):
            self.updates.append((str(statement), params))

        @staticmethod
        def commit():
            pass

    tenant_db = TenantDb()

    @contextmanager
    def tenant_session(_schema):
        yield tenant_db

    monkeypatch.setattr(local_connectors, "_connector_channel", lambda *_args: (7, 11))
    monkeypatch.setattr(local_connectors, "_tenant_schema", lambda *_args: "tenant_7")
    monkeypatch.setattr(local_connectors, "tenant_session", tenant_session)
    monkeypatch.setattr(local_connectors, "process_and_save_message", lambda **_kwargs: {
        "_created": False,
        "message_id": 42,
        "conversation_id": 99,
    })

    result = local_connectors.receive_local_connector_history(
        "instagram",
        {"messages": [{
            "threadId": "thread-1", "customerId": "thread-1", "messageId": "old-message",
            "direction": "inbound", "message": "Tin cũ", "createdAt": "2026-09-30T06:45:00Z",
        }]},
        "Bearer connector-token",
        object(),
    )

    assert result["duplicates"] == 1
    assert "SET received_at = :received_at" in tenant_db.updates[0][0]
    assert tenant_db.updates[0][1] == {
        "received_at": datetime(2026, 9, 30, 6, 45),
        "message_id": 42,
        "conversation_id": 99,
        "channel": "instagram",
    }


def test_live_meta_history_is_distinguished_from_backfill_and_gets_fallback_time():
    live = local_connectors._normalize_history_message("instagram", {
        "threadId": "thread-1", "customerId": "buyer-1", "messageId": "live-1",
        "direction": "inbound", "message": "Tin mới", "isLive": True,
    })
    old = local_connectors._normalize_history_message("instagram", {
        "threadId": "thread-1", "customerId": "buyer-1", "messageId": "old-1",
        "direction": "inbound", "message": "Tin cũ",
    })
    unsupported_live = local_connectors._normalize_history_message("shopee", {
        "threadId": "thread-1", "customerId": "buyer-1", "messageId": "market-1",
        "direction": "inbound", "message": "Tin Shopee", "isLive": True,
    })

    assert live["is_live"] is True
    assert live["created_at"] is not None
    assert old["is_live"] is False
    assert old["created_at"] is None
    assert unsupported_live["is_live"] is False


def test_live_meta_history_route_schedules_bot_and_broadcasts_message(monkeypatch):
    channel = type("ChannelRow", (), {
        "id": 11, "business_id": 7, "channel_type": "instagram",
        "status": "active", "external_account_id": "instagram-shop-7",
    })()

    class TenantDb:
        @staticmethod
        def get(_model, _channel_id):
            return channel

    @contextmanager
    def tenant_session(_schema):
        yield TenantDb()

    calls = []
    monkeypatch.setattr(local_connectors, "_connector_channel", lambda *_args: (7, 11))
    monkeypatch.setattr(local_connectors, "_tenant_schema", lambda *_args: "tenant_7")
    monkeypatch.setattr(local_connectors, "tenant_session", tenant_session)

    def persist(*, message, history_import, **_kwargs):
        calls.append((message, history_import))
        return {
            "_created": True,
            "message_id": 43,
            "conversation_id": 99,
            "external_message_id": message["external_message_id"],
            "direction": "inbound",
            "content": message["content"],
            "received_at": message["received_at"],
        }

    monkeypatch.setattr(local_connectors, "process_and_save_message", persist)
    captured = {}

    async def broadcast(event, *, business_id):
        captured.update(event=event, business_id=business_id)

    monkeypatch.setattr(local_connectors.manager, "broadcast", broadcast)
    response = asyncio.run(local_connectors.receive_shopee_tiktok_history(
        "instagram",
        {"messages": [{
            "threadId": "thread-1", "customerId": "buyer-1", "messageId": "live-1",
            "direction": "inbound", "message": "Tin mới", "isLive": True,
        }]},
        "Bearer connector-token",
        object(),
    ))

    assert response == {"status": "received", "imported": 1, "duplicates": 0, "skipped": 0}
    assert calls[0][1] is False  # Explicit live messages use the normal automation path.
    assert "history_import" not in calls[0][0]["raw_payload"]
    assert calls[0][0]["raw_payload"]["source"] == "meta_live_inbox"
    assert calls[0][0]["received_at"] is not None
    assert captured["business_id"] == 7
    assert captured["event"]["type"] == "message_created"
    assert captured["event"]["conversation_id"] == 99
    assert captured["event"]["message"]["message_id"] == 43


def test_live_meta_duplicate_promotes_history_message_to_idempotent_bot_turn(monkeypatch):
    channel = type("ChannelRow", (), {
        "id": 11, "business_id": 7, "channel_type": "facebook",
        "status": "active", "external_account_id": "facebook-shop-7",
    })()

    class TenantDb:
        @staticmethod
        def get(_model, _channel_id):
            return channel

    @contextmanager
    def tenant_session(_schema):
        yield TenantDb()

    scheduled = []
    monkeypatch.setattr(local_connectors, "_connector_channel", lambda *_args: (7, 11))
    monkeypatch.setattr(local_connectors, "_tenant_schema", lambda *_args: "tenant_7")
    monkeypatch.setattr(local_connectors, "tenant_session", tenant_session)
    monkeypatch.setattr(local_connectors, "process_and_save_message", lambda **_kwargs: {
        "_created": False, "message_id": 43, "conversation_id": 99,
    })
    monkeypatch.setattr(
        "app.services.conversation_turn_service.schedule_chatbot_turn",
        lambda db, **kwargs: scheduled.append(kwargs),
    )

    result = local_connectors.receive_local_connector_history(
        "facebook",
        {"messages": [{
            "threadId": "thread-1", "customerId": "buyer-1", "messageId": "live-1",
            "direction": "inbound", "message": "Tin mới", "isLive": True,
        }]},
        "Bearer connector-token",
        object(),
    )

    assert result == {"status": "received", "imported": 0, "duplicates": 1, "skipped": 0}
    assert scheduled == [{"business_id": 7, "conversation_id": 99, "message_id": 43}]


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


def test_history_import_keeps_unavailable_timestamp_unknown_instead_of_using_import_time():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Business.metadata.create_all(engine)
    with Session(engine) as db:
        business = Business(name="Unknown Time Shop", slug="unknown-time-shop")
        db.add(business)
        db.flush()
        channel = Channel(
            business_id=business.id,
            channel_type="instagram",
            name="Instagram",
            external_account_id="instagram-unknown-time",
            status="active",
        )
        db.add(channel)
        db.flush()
        message = {
            "channel": "instagram", "business_id": business.id, "channel_id": channel.id,
            "external_account_id": channel.external_account_id, "external_user_id": "buyer-unknown-time",
            "external_message_id": "instagram:unknown-time-1", "direction": "inbound",
            "content": "Old message with no timestamp from Meta", "received_at": None,
            "raw_payload": {"threadId": "thread-unknown-time", "history_import": True},
        }

        saved = process_and_save_message(db, message, history_import=True)
        stored = db.scalar(select(Message).where(Message.external_message_id == "instagram:unknown-time-1"))
        conversation = db.scalar(select(Conversation))

        assert saved["_created"] is True
        assert stored.received_at is None
        assert stored.raw_payload["timestamp_accuracy"] == "unavailable_from_source"
        assert conversation.last_message_at is None


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
