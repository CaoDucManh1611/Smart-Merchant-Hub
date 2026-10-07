import asyncio
from concurrent.futures import Future
import hashlib
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile

import pytest
from fastapi import HTTPException
from starlette.responses import Response

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import shopee_bot
import connector_pairing
import server_connector_agent
from shopee_bot import normalize_message


def test_shopee_bridge_timeout_is_delivery_unknown_not_send_failure():
    pending = Future()
    with pytest.raises(shopee_bot.ShopeeDeliveryUnknown, match="chưa xác nhận"):
        shopee_bot.await_bridge_result(pending, timeout=0.001)
    pending.cancel()

from app.api import conversations, local_connectors, onboarding
from app.api.local_connectors import (
    _code_parts,
    create_connector_app_download_ticket,
    download_connector_app_with_ticket,
    download_local_connector_app,
    download_local_connector_bundle_legacy,
)
from app.services.channel_credentials import decrypt_token


def _assert_connector_zip(response, executable_name, *, include_download_header=True):
    assert isinstance(response, Response)
    assert response.media_type == "application/zip"
    if include_download_header:
        assert executable_name.removesuffix(".exe") + ".zip" in response.headers["content-disposition"]
    else:
        assert "content-disposition" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    with ZipFile(BytesIO(response.body)) as bundle:
        assert executable_name in bundle.namelist()
        assert bundle.read(executable_name).startswith(b"MZ")
        assert "HUONG-DAN.txt" in bundle.namelist()


@pytest.mark.parametrize("channel", ["tiktok", "shopee", "facebook", "instagram"])
def test_pairing_and_connector_codes_are_shop_scoped(channel):
    code = f"PAIR.{channel}.12.34.abcdEFGHijkl_1234"
    assert _code_parts(code, "PAIR") == (channel, 12, 34, "abcdEFGHijkl_1234")

    token = f"CONN.{channel}.12.34.abcdEFGHijkl_1234"
    assert _code_parts(token, "CONN", channel) == (channel, 12, 34, "abcdEFGHijkl_1234")


def test_pair_request_keeps_local_mode_as_compatibility_default():
    request = local_connectors.PairConnectorRequest(pairing_code="PAIR.shopee.12.34.abcdEFGHijkl_1234")
    assert request.execution_mode == "local"


def test_server_viewer_input_rejects_unbounded_or_unsupported_actions():
    assert local_connectors.ServerViewerInput(action="click", x=1200, y=800).action == "click"
    with pytest.raises(Exception):
        local_connectors.ServerViewerInput(action="navigate", url="https://example.com")
    with pytest.raises(Exception):
        local_connectors.ServerViewerInput(action="click", x=10001, y=0)


def test_server_viewer_ticket_is_scoped_and_stored_only_as_a_hash(monkeypatch):
    ticket = "viewer-ticket-value"
    channel = type("ChannelRow", (), {
        "id": 11,
        "business_id": 7,
        "channel_type": "instagram",
        "status": "active",
        "config": {
            "connector_execution_mode": "server",
            "server_viewer_ticket_hash": hashlib.sha256(ticket.encode()).hexdigest(),
            "server_viewer_ticket_expires_at": int(__import__("time").time()) + 100,
        },
    })()

    class TenantDb:
        @staticmethod
        def scalar(_query): return channel

    @contextmanager
    def tenant_session(_schema):
        yield TenantDb()

    monkeypatch.setattr(local_connectors, "_tenant_schema", lambda *_args: "tenant_7")
    monkeypatch.setattr(local_connectors, "tenant_session", tenant_session)
    _, config = local_connectors._server_viewer_channel(7, "instagram", 11, f"Bearer {ticket}", object())
    assert config["server_viewer_ticket_hash"] != ticket
    with pytest.raises(HTTPException) as error:
        local_connectors._server_viewer_channel(7, "instagram", 11, "Bearer incorrect-ticket", object())
    assert error.value.status_code == 401


def test_server_agent_uses_stable_shop_scoped_ports_and_restricts_channels(tmp_path, monkeypatch):
    monkeypatch.setattr(server_connector_agent, "DATA_ROOT", tmp_path)
    first = server_connector_agent._worker_ports((7, "shopee", 11))
    assert first == server_connector_agent._worker_ports((7, "shopee", 11))
    assert first != server_connector_agent._worker_ports((7, "tiktok", 11))
    with pytest.raises(ValueError):
        server_connector_agent._safe_key(7, "whatsapp", 11)


def test_server_agent_authorizes_internal_routes_and_scopes_worker_lookup(monkeypatch):
    monkeypatch.setattr(server_connector_agent, "AGENT_TOKEN", "agent-test-secret")
    assert server_connector_agent._authorized({"X-Server-Connector-Agent-Token": "agent-test-secret"})
    assert not server_connector_agent._authorized({"X-Server-Connector-Agent-Token": "wrong"})

    class Process:
        @staticmethod
        def poll(): return None

    record = {"key": (7, "shopee", 11), "process": Process()}
    monkeypatch.setattr(server_connector_agent, "workers", {(7, "shopee", 11): record})
    assert server_connector_agent._record_for_path(["internal", "channels", "7", "shopee", "11", "send"]) is record
    assert server_connector_agent._record_for_path(["internal", "channels", "7", "tiktok", "11", "send"]) is None


def test_server_agent_http_routes_require_shared_secret(monkeypatch):
    monkeypatch.setattr(server_connector_agent, "AGENT_TOKEN", "agent-test-secret")
    server = server_connector_agent.ThreadingHTTPServer(("127.0.0.1", 0), server_connector_agent.AgentHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(f"{base_url}/health", timeout=2) as response:
            assert json.loads(response.read()) == {"status": "ok", "agent": "windows"}
        with pytest.raises(HTTPError) as unauthorized:
            urlopen(f"{base_url}/internal/channels/7/shopee/11/screenshot", timeout=2)
        assert unauthorized.value.code == 401
        request = Request(
            f"{base_url}/internal/channels/7/shopee/11/screenshot",
            headers={"X-Server-Connector-Agent-Token": "agent-test-secret"},
        )
        with pytest.raises(HTTPError) as not_ready:
            urlopen(request, timeout=2)
        assert not_ready.value.code == 503
    finally:
        server.shutdown()
        server.server_close()


def test_server_pairing_helper_opens_ticket_viewer_without_persisting_connector_token(tmp_path, monkeypatch):
    package = tmp_path / "bundle"
    runtime = tmp_path / "runtime"
    package.mkdir()
    (package / "connector_defaults.json").write_text(json.dumps({
        "backend_url": "https://crm.example/api",
        "frontend_url": "https://crm.example",
        "execution_mode": "server",
    }), encoding="utf-8")
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        @staticmethod
        def read():
            return json.dumps({
                "channel_type": "shopee", "business_id": 7, "channel_id": 11,
                "server_managed": True, "viewer_ticket": "opaque-one-time-ticket",
            }).encode()
    monkeypatch.setattr(connector_pairing, "urlopen", lambda *_args, **_kwargs: Response())
    opened = []
    monkeypatch.setattr(connector_pairing.webbrowser, "open", lambda url: opened.append(url) or True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "PAIR.shopee.7.11.abcdEFGHijkl_1234")

    with pytest.raises(SystemExit) as result:
        connector_pairing.configure_local_connector("shopee", runtime, package)

    assert result.value.code == 0
    assert not (runtime / "connector_config.json").exists()
    assert opened and "server-connector-viewer.html#" in opened[0]
    assert "opaque-one-time-ticket" in opened[0]


@pytest.mark.parametrize("channel", ["facebook", "instagram"])
def test_meta_chat_connectors_do_not_enable_marketplace_order_import(channel):
    payload = local_connectors.ConnectorOrderBatch.model_validate({"orders": [{
        "external_order_id": "meta-order-1",
        "total_amount": 10,
        "items": [{"name": "placeholder", "quantity": 1, "unit_price": 10}],
    }]})

    with pytest.raises(HTTPException) as error:
        local_connectors.receive_local_connector_orders(channel, payload, None, object())

    assert error.value.status_code == 404


def test_connector_heartbeat_updates_only_the_authenticated_shop(monkeypatch):
    channel = type("ChannelRow", (), {
        "id": 11,
        "business_id": 7,
        "channel_type": "tiktok",
        "status": "active",
        "config": {"provider": "tiktok_local_connector"},
    })()

    class TenantDb:
        @staticmethod
        def scalar(_query):
            return channel

        @staticmethod
        def commit():
            pass

    @contextmanager
    def tenant_session(_schema):
        yield TenantDb()

    monkeypatch.setattr(local_connectors, "_connector_channel", lambda *_args: (7, 11))
    monkeypatch.setattr(local_connectors, "_tenant_schema", lambda *_args: "tenant_7")
    monkeypatch.setattr(local_connectors, "tenant_session", tenant_session)

    result = local_connectors.report_connector_heartbeat(
        "tiktok",
        local_connectors.ConnectorHeartbeatRequest(state="error", error_code="edge_session_locked"),
        "Bearer connector-token",
        object(),
    )

    assert result == {"status": "recorded", "connector_status": "error"}
    assert channel.config["connector_status"] == "error"
    assert channel.config["connector_last_error_code"] == "edge_session_locked"
    assert channel.config["connector_last_seen_at"]


def test_connector_status_report_sends_only_bounded_error_code(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read():
            return b'{"status":"recorded"}'

    def fake_urlopen(request, timeout):
        captured.update(
            url=request.full_url,
            auth=request.get_header("Authorization"),
            body=request.data,
            timeout=timeout,
        )
        return Response()

    monkeypatch.setattr(connector_pairing, "urlopen", fake_urlopen)
    connector_pairing.report_connector_status(
        "shopee", "https://crm.example/", "secret-token", state="error", error_code="edge_locked"
    )

    assert captured["url"] == "https://crm.example/api/channels/shopee/heartbeat"
    assert captured["auth"] == "Bearer secret-token"
    assert captured["body"] == b'{"state": "error", "error_code": "edge_locked"}'
    assert captured["timeout"] == 3


def test_visible_marketplace_order_parser_keeps_order_and_item_without_buyer_pii():
    order = connector_pairing.normalize_visible_order_card("shopee", {
        "orderId": "250101ABCDEF",
        "status": "Chờ lấy hàng",
        "text": "Mã đơn hàng\n250101ABCDEF\nTổng số tiền Người mua thanh toán\n₫349.000\nChờ lấy hàng",
        "productBlocks": ["AULA F75 Pro\nSKU: F75-PRO\nx1\n₫349.000"],
        "createdAt": "2026-10-06T10:15:00Z",
    })

    assert order["external_order_id"] == "250101ABCDEF"
    assert order["source_status"] == "Chờ lấy hàng"
    assert order["total_amount"] == 349000
    assert order["items"] == [{
        "external_product_id": None,
        "sku": "F75-PRO",
        "name": "AULA F75 Pro",
        "quantity": 1,
        "unit_price": 349000,
    }]
    assert "buyer_name" not in order and "phone" not in order


def test_order_checkpoint_is_shop_scoped_and_atomic(tmp_path):
    first = connector_pairing.order_checkpoint_path(tmp_path, "shopee", "CONN.shopee.shop-1.secret")
    second = connector_pairing.order_checkpoint_path(tmp_path, "shopee", "CONN.shopee.shop-2.secret")
    checkpoint = connector_pairing.load_order_checkpoint(first)

    orders = [
        {"external_order_id": "order-1", "source_status": "pending"},
        {"external_order_id": "order-2", "source_status": "pending"},
    ]
    assert connector_pairing.marketplace_orders_pending(checkpoint, orders) == orders
    saved = connector_pairing.save_order_checkpoint(first, checkpoint, orders)

    assert first != second
    assert connector_pairing.load_order_checkpoint(first) == saved
    assert saved["synced_order_ids"] == ["order-1", "order-2"]
    assert connector_pairing.marketplace_orders_pending(saved, orders) == []
    changed = [{**orders[0], "source_status": "shipped"}]
    assert connector_pairing.marketplace_orders_pending(saved, changed) == changed


def test_marketplace_orders_import_as_drafts_and_repeat_sync_is_idempotent(monkeypatch):
    channel = type("ChannelRow", (), {
        "id": 11,
        "business_id": 7,
        "channel_type": "shopee",
        "status": "active",
        "external_account_id": "shop-1",
    })()

    class TenantDb:
        def __init__(self):
            self.added = []
            self.next_id = 1

        @staticmethod
        def get(_model, _key):
            return channel

        def scalar(self, statement):
            sql = str(statement)
            if "FROM orders" in sql:
                key = statement.compile().params.get("order_number_1")
                return next((row for row in self.added if isinstance(row, local_connectors.Order) and row.order_number == key), None)
            if "FROM customers" in sql:
                key = statement.compile().params.get("external_user_id_1")
                return next((row for row in self.added if isinstance(row, local_connectors.Customer) and row.external_user_id == key), None)
            return None

        def add(self, row):
            if getattr(row, "id", None) is None:
                row.id = self.next_id
                self.next_id += 1
            self.added.append(row)

        @staticmethod
        def flush():
            pass

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
    payload = local_connectors.ConnectorOrderBatch.model_validate({"orders": [{
        "external_order_id": "250101ABCDEF",
        "source_status": "Chờ lấy hàng",
        "total_amount": "349000",
        "items": [{"sku": "F75-PRO", "name": "AULA F75 Pro", "quantity": 1, "unit_price": "349000"}],
    }]})

    first = local_connectors.receive_local_connector_orders("shopee", payload, "Bearer token", object())
    second = local_connectors.receive_local_connector_orders("shopee", payload, "Bearer token", object())
    another_order = local_connectors.ConnectorOrderBatch.model_validate({"orders": [{
        "external_order_id": "250101SECOND",
        "total_amount": "1000",
        "items": [{"name": "Sản phẩm khác", "quantity": 1, "unit_price": "1000"}],
    }]})
    third = local_connectors.receive_local_connector_orders("shopee", another_order, "Bearer token", object())

    order = next(row for row in tenant_db.added if isinstance(row, local_connectors.Order))
    customer = next(row for row in tenant_db.added if isinstance(row, local_connectors.Customer))
    product = next(row for row in tenant_db.added if isinstance(row, local_connectors.Product))
    item = next(row for row in tenant_db.added if isinstance(row, local_connectors.OrderItem))
    assert first == {"status": "received", "created": 1, "updated": 0, "duplicates": 0}
    assert second == {"status": "received", "created": 0, "updated": 1, "duplicates": 0}
    assert third["created"] == 1
    assert order.status == "draft" and order.metadata_["external_order_id"] == "250101ABCDEF"
    assert customer.phone is None and customer.address is None
    assert len([row for row in tenant_db.added if isinstance(row, local_connectors.Customer)]) == 1
    assert product.status == "external" and product.stock_quantity == 0
    assert item.product_name_snapshot == "AULA F75 Pro" and item.line_total == 349000


def test_connector_retry_is_acknowledged_only_for_the_current_request(monkeypatch):
    channel = type("ChannelRow", (), {
        "id": 11,
        "business_id": 7,
        "channel_type": "tiktok",
        "status": "active",
        "config": {
            "connector_retry_id": "retry-1234567890",
            "connector_retry_requested_at": datetime.now(timezone.utc).isoformat(),
        },
    })()

    class TenantDb:
        @staticmethod
        def scalar(_query):
            return channel

        @staticmethod
        def commit():
            pass

    @contextmanager
    def tenant_session(_schema):
        yield TenantDb()

    monkeypatch.setattr(local_connectors, "_connector_channel", lambda *_args: (7, 11))
    monkeypatch.setattr(local_connectors, "_tenant_schema", lambda *_args: "tenant_7")
    monkeypatch.setattr(local_connectors, "tenant_session", tenant_session)

    pending = local_connectors.report_connector_heartbeat(
        "tiktok", local_connectors.ConnectorHeartbeatRequest(), "Bearer connector-token", object()
    )
    assert pending["retry_id"] == "retry-1234567890"

    acknowledged = local_connectors.report_connector_heartbeat(
        "tiktok",
        local_connectors.ConnectorHeartbeatRequest(retry_ack_id="retry-1234567890"),
        "Bearer connector-token",
        object(),
    )
    assert acknowledged["retry_acknowledged"] is True
    assert "connector_retry_id" not in channel.config


def test_retry_command_restarts_only_after_server_ack(monkeypatch):
    calls = []
    monkeypatch.setattr(connector_pairing, "report_connector_status", lambda *args, **kwargs: {"retry_acknowledged": True})
    monkeypatch.setattr(connector_pairing, "_restart_connector_process", lambda: calls.append("restart"))

    assert connector_pairing._acknowledge_retry_and_restart("tiktok", "https://crm.example", "token", "retry-1")
    assert calls == ["restart"]


def test_shop_admin_retry_queues_restart_only_for_a_live_paired_connector(monkeypatch):
    channel = type("ChannelRow", (), {
        "id": 11,
        "business_id": 7,
        "channel_type": "shopee",
        "status": "active",
        "config": {
            "provider": "shopee_local_connector",
            "connector_paired_at": 123,
            "connector_last_seen_at": datetime.now(timezone.utc).isoformat(),
        },
    })()

    class TenantDb:
        @staticmethod
        def scalar(_query):
            return channel

    class PlatformSession:
        @staticmethod
        def commit():
            pass

    @contextmanager
    def tenant_session(_schema):
        yield TenantDb()

    monkeypatch.setattr(onboarding, "_require_shop_admin", lambda *_args: None)
    monkeypatch.setattr(onboarding, "tenant_session", tenant_session)
    monkeypatch.setattr(onboarding, "record_audit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(onboarding, "schema_name_for", lambda _business_id: "shop_7")
    result = onboarding.retry_local_connector(7, "shopee", PlatformSession(), type("User", (), {"id": 3})())

    assert result["status"] == "retry_queued"
    assert result["requires_local_device"] is True
    assert channel.config["connector_retry_id"]
    assert channel.config["connector_retry_requested_at"]


def test_shop_admin_retry_explains_offline_connector(monkeypatch):
    channel = type("ChannelRow", (), {
        "business_id": 7,
        "channel_type": "tiktok",
        "status": "active",
        "config": {
            "provider": "tiktok_local_connector",
            "connector_paired_at": 123,
            "connector_last_seen_at": "2020-01-01T00:00:00+00:00",
        },
    })()

    class TenantDb:
        @staticmethod
        def scalar(_query):
            return channel

    @contextmanager
    def tenant_session(_schema):
        yield TenantDb()

    monkeypatch.setattr(onboarding, "_require_shop_admin", lambda *_args: None)
    monkeypatch.setattr(onboarding, "tenant_session", tenant_session)
    monkeypatch.setattr(onboarding, "schema_name_for", lambda _business_id: "shop_7")
    with pytest.raises(HTTPException, match="ngoại tuyến"):
        onboarding.retry_local_connector(7, "tiktok", object(), type("User", (), {"id": 3})())


@pytest.mark.parametrize("channel_type", ["facebook", "instagram", "tiktok", "shopee"])
def test_pairing_code_requires_explicit_disconnect_for_already_paired_connector(monkeypatch, channel_type):
    channel = type("ChannelRow", (), {
        "id": 11,
        "business_id": 7,
        "channel_type": channel_type,
        "status": "active",
        "access_token_encrypted": "encrypted-connector-token",
        "config": {
            "provider": f"{channel_type}_local_connector",
            "connector_paired_at": 123,
            "connector_last_seen_at": "2020-01-01T00:00:00+00:00",
        },
    })()

    class TenantDb:
        @staticmethod
        def scalar(_query):
            return channel

    class PlatformSession:
        @staticmethod
        def rollback():
            pass

    @contextmanager
    def tenant_session(_schema):
        yield TenantDb()

    monkeypatch.setattr(onboarding, "_require_shop_admin", lambda *_args: None)
    monkeypatch.setattr(onboarding, "tenant_session", tenant_session)
    monkeypatch.setattr(onboarding, "schema_name_for", lambda _business_id: "shop_7")

    with pytest.raises(HTTPException) as error:
        onboarding.create_local_connector_pairing_code(
            7, channel_type, object(), PlatformSession(), type("User", (), {"id": 3})()
        )

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "connector_already_paired"
    assert "ngắt kết nối" in error.value.detail["message"].lower()


def test_shop_admin_retry_rejects_non_local_channel(monkeypatch):
    channel = type("ChannelRow", (), {
        "business_id": 7,
        "channel_type": "tiktok",
        "status": "active",
        "config": {
            "provider": "official_tiktok_api",
            "connector_paired_at": 123,
            "connector_last_seen_at": datetime.now(timezone.utc).isoformat(),
        },
    })()

    class TenantDb:
        @staticmethod
        def scalar(_query):
            return channel

    @contextmanager
    def tenant_session(_schema):
        yield TenantDb()

    monkeypatch.setattr(onboarding, "_require_shop_admin", lambda *_args: None)
    monkeypatch.setattr(onboarding, "tenant_session", tenant_session)
    monkeypatch.setattr(onboarding, "schema_name_for", lambda _business_id: "shop_7")
    with pytest.raises(HTTPException) as error:
        onboarding.retry_local_connector(7, "tiktok", object(), type("User", (), {"id": 3})())
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "connector_not_paired"


def test_connector_rejects_wrong_type_and_malformed_tokens():
    with pytest.raises(HTTPException) as wrong_type:
        _code_parts("CONN.shopee.12.34.abcdEFGHijkl_1234", "CONN", "tiktok")
    assert wrong_type.value.status_code == 401

    with pytest.raises(HTTPException) as malformed:
        _code_parts("CONN.tiktok.12.34.bad", "CONN")
    assert malformed.value.status_code == 401


@pytest.mark.parametrize(
    ("channel", "filename"),
    [
        ("tiktok", "SmartMerchantTikTok.exe"),
        ("shopee", "SmartMerchantShopee.exe"),
        ("facebook", "SmartMerchantMessenger.exe"),
        ("instagram", "SmartMerchantInstagram.exe"),
    ],
)
def test_connector_download_serves_zip_with_the_executable(channel, filename, tmp_path, monkeypatch):
    executable = tmp_path / filename
    executable.write_bytes(b"MZ" + b"0" * (1024 * 1024))
    monkeypatch.setattr(local_connectors, "_connector_exe_path", lambda _: executable)

    response = download_local_connector_app(channel)

    _assert_connector_zip(response, filename)
    if channel in {"facebook", "instagram"}:
        with ZipFile(BytesIO(response.body)) as bundle:
            instructions = bundle.read("HUONG-DAN.txt").decode("utf-8")
        assert "chỉ nhập lịch sử lần đầu hoặc phần còn thiếu" in instructions
        assert "sau khi lịch sử hoàn tất sẽ chỉ đồng bộ tin mới" in instructions
        assert "ứng dụng hỏi trước" not in instructions


def test_connector_download_reports_missing_executable(monkeypatch):
    monkeypatch.setattr(local_connectors, "_connector_exe_path", lambda _: None)

    with pytest.raises(HTTPException) as missing:
        download_local_connector_app("shopee")

    assert missing.value.status_code == 503


def test_connector_download_ticket_is_expiring_and_channel_scoped(tmp_path, monkeypatch):
    executable = tmp_path / "SmartMerchantTikTok.exe"
    executable.write_bytes(b"MZ" + b"0" * (1024 * 1024))
    monkeypatch.setattr(local_connectors, "_connector_exe_path", lambda _: executable)
    monkeypatch.setattr(local_connectors.settings, "CHANNEL_ENCRYPTION_KEY", "test-download-key")
    now = 1_800_000_000
    monkeypatch.setattr(local_connectors.time, "time", lambda: now)

    ticket = create_connector_app_download_ticket("tiktok")["ticket"]
    payload = json.loads(decrypt_token(ticket, "test-download-key"))

    assert payload == {"purpose": "connector_app", "channel_type": "tiktok", "expires_at": now + 300}
    response = download_connector_app_with_ticket("tiktok", ticket)
    _assert_connector_zip(response, "SmartMerchantTikTok.exe", include_download_header=False)

    with pytest.raises(HTTPException) as wrong_channel:
        download_connector_app_with_ticket("shopee", ticket)
    assert wrong_channel.value.status_code == 404

    monkeypatch.setattr(local_connectors.time, "time", lambda: now + 300)
    with pytest.raises(HTTPException) as expired:
        download_connector_app_with_ticket("tiktok", ticket)
    assert expired.value.status_code == 404


def test_legacy_bundle_download_also_serves_the_zip(tmp_path, monkeypatch):
    executable = tmp_path / "SmartMerchantTikTok.exe"
    executable.write_bytes(b"MZ" + b"0" * (1024 * 1024))
    monkeypatch.setattr(local_connectors, "_connector_exe_path", lambda _: executable)

    _assert_connector_zip(download_local_connector_bundle_legacy("tiktok"), "SmartMerchantTikTok.exe")


def test_shopee_incoming_new_webchat_message_is_not_dropped():
    message = normalize_message({
        "message_id": "msg-1",
        "conversation_id": "conversation-1",
        "from_id": "customer-1",
        "send_by_yourself": False,
        "source": "new_webchat",
        "message_type": "text",
        "content": {"text": "Hello shop"},
    })

    assert message["messageId"] == "msg-1"
    assert message["threadId"] == "conversation-1"
    assert message["message"] == "Hello shop"


def test_shopee_realtime_message_during_history_scan_is_importable_as_history():
    conversation = {
        "threadId": "conversation-1", "customerId": "customer-1", "displayName": "Buyer",
    }
    realtime_message = {
        "threadId": "conversation-1", "messageId": "msg-old", "message": "Tin cũ",
        "messageType": "text", "createdAt": "2026-10-01T10:00:00Z",
    }

    history_message = shopee_bot.normalize_live_message_as_history(realtime_message, conversation)

    assert history_message["threadId"] == "conversation-1"
    assert history_message["customerId"] == "customer-1"
    assert history_message["messageId"] == "msg-old"
    assert history_message["direction"] == "inbound"
    assert history_message["message"] == "Tin cũ"


def test_shopee_system_card_does_not_become_customer_question(monkeypatch):
    monkeypatch.setattr(local_connectors, "_connector_channel", lambda *_args: (7, 11))
    monkeypatch.setattr(
        local_connectors, "process_and_save_message",
        lambda **_kwargs: pytest.fail("system card must not be saved as customer chat"),
    )

    result = asyncio.run(local_connectors.receive_local_connector_message(
        "shopee",
        {
            "authorId": "buyer-1", "threadId": "thread-42", "messageId": "card-1",
            "message": "[out_of_stock_reminder_card]",
            "messageType": "out_of_stock_reminder_card",
        },
        "Bearer connector-token",
        object(),
    ))

    assert result == {"status": "ignored", "processed": 0}


def test_local_connector_persists_thread_id_for_outbound_replies(monkeypatch):
    captured = {}
    channel = type("ChannelRow", (), {
        "business_id": 7,
        "channel_type": "tiktok",
        "status": "active",
        "external_account_id": "shop-account",
    })()

    class TenantDb:
        def get(self, _model, _channel_id):
            return channel

    @contextmanager
    def tenant_session(_schema):
        yield TenantDb()

    def save_message(*, message, **_kwargs):
        captured.update(message)
        return {"_created": False}

    monkeypatch.setattr(local_connectors, "_connector_channel", lambda *_args: (7, 11))
    monkeypatch.setattr(local_connectors, "_tenant_schema", lambda *_args: "tenant_7")
    monkeypatch.setattr(local_connectors, "tenant_session", tenant_session)
    monkeypatch.setattr(local_connectors, "process_and_save_message", save_message)

    asyncio.run(local_connectors.receive_local_connector_message(
        "tiktok",
        {
            "authorId": "buyer-1", "threadId": "thread-42", "messageId": "msg-1",
            "message": "Hi", "avatarUrl": "https://cdn.example/buyer.png",
        },
        "Bearer connector-token",
        object(),
    ))

    assert captured["raw_payload"]["threadId"] == "thread-42"
    assert captured["avatar_url"] == "https://cdn.example/buyer.png"


@pytest.mark.parametrize(
    ("channel_type", "sync_profiles"),
    [
        ("shopee", local_connectors.sync_shopee_customer_avatars),
        ("tiktok", local_connectors.sync_tiktok_customer_avatars),
    ],
)
def test_connector_avatar_sync_only_fills_avatar_for_existing_shop_customer(monkeypatch, channel_type, sync_profiles):
    channel = type("ChannelRow", (), {"external_account_id": "shop-7"})()
    customer = type("CustomerRow", (), {"id": 10, "business_id": 7, "avatar_url": None})()
    identity = type("IdentityRow", (), {"external_user_id": "buyer-1", "customer": customer})()

    class Rows:
        @staticmethod
        def all():
            return [identity]

    class TenantDb:
        @staticmethod
        def get(_model, _channel_id):
            return channel

        @staticmethod
        def scalars(_query):
            return Rows()

        @staticmethod
        def commit():
            pass

        @staticmethod
        def add(_row):
            pass

    @contextmanager
    def tenant_session(_schema):
        yield TenantDb()

    monkeypatch.setattr(local_connectors, "_connector_channel", lambda actual, *_args: (7, 11) if actual == channel_type else pytest.fail("wrong channel"))
    monkeypatch.setattr(local_connectors, "_tenant_schema", lambda *_args: "tenant_7")
    monkeypatch.setattr(local_connectors, "tenant_session", tenant_session)

    result = sync_profiles(
        {"profiles": [{"externalUserId": "buyer-1", "avatarUrl": "https://cdn.example/buyer"}]},
        "Bearer connector-token",
        object(),
    )

    assert result == {
        "status": "synced",
        "updated": 1,
        "matchedExternalUserIds": ["buyer-1"],
    }
    assert customer.avatar_url == "https://cdn.example/buyer"


def test_meta_instagram_profile_sync_repairs_an_existing_avatar(monkeypatch):
    channel = type("ChannelRow", (), {"external_account_id": "meta-ig-account"})()
    customer = type("CustomerRow", (), {
        "id": 31, "business_id": 7, "avatar_url": "https://old-cdn.example/expired.jpg",
    })()
    identity = type("IdentityRow", (), {"external_user_id": "ig-thread-31", "customer": customer})()

    class Rows:
        @staticmethod
        def all():
            return [identity]

    class TenantDb:
        @staticmethod
        def get(_model, _channel_id):
            return channel

        @staticmethod
        def scalars(_query):
            return Rows()

        @staticmethod
        def commit():
            pass

        @staticmethod
        def add(_row):
            pass

    @contextmanager
    def tenant_session(_schema):
        yield TenantDb()

    monkeypatch.setattr(local_connectors, "_connector_channel", lambda actual, *_args: (7, 12) if actual == "instagram" else pytest.fail("wrong channel"))
    monkeypatch.setattr(local_connectors, "_tenant_schema", lambda *_args: "tenant_7")
    monkeypatch.setattr(local_connectors, "tenant_session", tenant_session)

    result = local_connectors.sync_meta_instagram_customer_avatars(
        {"profiles": [{"externalUserId": "ig-thread-31", "avatarUrl": "https://new-cdn.example/profile.jpg"}]},
        "Bearer connector-token",
        object(),
    )

    assert result == {
        "status": "synced",
        "updated": 1,
        "matchedExternalUserIds": ["ig-thread-31"],
    }
    assert customer.avatar_url == "https://new-cdn.example/profile.jpg"


def test_shopee_normalizer_accepts_string_content_and_sender_aliases():
    message = normalize_message({
        "msg_id": "msg-3",
        "conv_id": "conversation-2",
        "sender_id": "customer-2",
        "send_by_yourself": False,
        "message_type": "text",
        "content": '{"text":"Need help"}',
    })

    assert message["messageId"] == "msg-3"
    assert message["threadId"] == "conversation-2"
    assert message["authorId"] == "customer-2"
    assert message["message"] == "Need help"


def test_shopee_normalizer_forwards_sender_avatar():
    message = normalize_message({
        "id": "msg-avatar",
        "conversation_id": "conversation-avatar",
        "from_id": "customer-avatar",
        "from_user_avatar": "https://cf.shopee.vn/file/customer-avatar",
        "content": {"text": "Hello"},
    })

    assert message["avatarUrl"] == "https://cf.shopee.vn/file/customer-avatar"


def test_shopee_normalizer_extracts_nested_avatar_url():
    message = normalize_message({
        "id": "msg-avatar-nested",
        "conversation_id": "conversation-avatar",
        "from_id": "customer-avatar",
        "sender": {"avatar": {"url_list": ["//cf.shopee.vn/file/customer-avatar"]}},
        "content": {"text": "Hello"},
    })

    assert message["avatarUrl"] == "https://cf.shopee.vn/file/customer-avatar"


def test_shopee_connector_still_ignores_own_messages():
    assert normalize_message({
        "id": "msg-2",
        "conversation_id": "conversation-1",
        "from_id": "shop-1",
        "send_by_yourself": True,
        "content": {"text": "Shop reply"},
    }) is None
    assert normalize_message({
        "id": "msg-4",
        "conversation_id": "conversation-1",
        "from_id": "shop-1",
        "send_by_yourself": "1",
        "content": {"text": "Shop reply"},
    }) is None


def test_shopee_send_uses_shop_connector_and_platform_thread(monkeypatch):
    channel = type("ChannelRow", (), {"access_token_encrypted": "encrypted-token"})()

    class TenantDb:
        def scalar(self, _query):
            return channel

    response = type("Response", (), {
        "status_code": 200,
        "json": lambda _self: {"status": "sent", "message_id": "shopee-ui:thread-1:123"},
    })()
    sent = {}
    monkeypatch.setattr(conversations, "_local_connector_thread_id", lambda *_args: "thread-1")
    monkeypatch.setattr(conversations, "decrypt_token", lambda *_args: "connector-token")
    monkeypatch.setattr(conversations.settings, "SHOPEE_BRIDGE_CONTROL_URL", "http://host.docker.internal:8092")
    monkeypatch.setattr(conversations.httpx, "post", lambda url, **kwargs: (sent.update(url=url, **kwargs) or response))

    result, returned_channel = conversations.send_shopee_text(
        db=TenantDb(),
        conversation={"id": 22, "channel_id": 11},
        recipient_id="buyer-1",
        text_content="Chào bạn",
        business_id=7,
    )

    assert result["status"] == "sent"
    assert returned_channel is channel
    assert sent["url"] == "http://host.docker.internal:8092/send"
    assert sent["headers"]["X-Shopee-Bridge-Secret"] == "connector-token"
    assert sent["json"] == {"threadId": "thread-1", "message": "Chào bạn", "recipientId": "buyer-1"}


def test_server_managed_shopee_send_routes_through_private_agent(monkeypatch):
    channel = type("ChannelRow", (), {
        "id": 11,
        "access_token_encrypted": "encrypted-token",
        "config": {"connector_execution_mode": "server"},
    })()

    class TenantDb:
        @staticmethod
        def scalar(_query): return channel

    response = type("Response", (), {"status_code": 200, "json": lambda _self: {"status": "sent"}})()
    sent = {}
    monkeypatch.setattr(conversations, "_local_connector_thread_id", lambda *_args: "thread-1")
    monkeypatch.setattr(conversations, "decrypt_token", lambda *_args: "connector-token")
    monkeypatch.setattr(conversations.settings, "SERVER_CONNECTOR_AGENT_URL", "http://host.docker.internal:8095")
    monkeypatch.setattr(conversations.settings, "SERVER_CONNECTOR_AGENT_TOKEN", "agent-secret")
    monkeypatch.setattr(conversations.httpx, "post", lambda url, **kwargs: (sent.update(url=url, **kwargs) or response))

    result, _ = conversations.send_shopee_text(
        db=TenantDb(), conversation={"id": 22, "channel_id": 11}, recipient_id="buyer-1",
        text_content="Chào bạn", business_id=7,
    )

    assert result == {"status": "sent"}
    assert sent["url"] == "http://host.docker.internal:8095/internal/channels/7/shopee/11/send"
    assert sent["headers"] == {"X-Server-Connector-Agent-Token": "agent-secret"}


@pytest.mark.parametrize(
    ("channel_type", "setting_name", "port"),
    [
        ("facebook", "META_MESSENGER_BRIDGE_CONTROL_URL", 8093),
        ("instagram", "META_INSTAGRAM_BRIDGE_CONTROL_URL", 8094),
    ],
)
def test_meta_local_connector_sends_reply_to_channel_specific_bridge(monkeypatch, channel_type, setting_name, port):
    channel = type("ChannelRow", (), {
        "id": 11,
        "access_token_encrypted": "encrypted-token",
        "config": {"provider": f"{channel_type}_local_connector"},
    })()

    class TenantDb:
        @staticmethod
        def scalar(_query):
            return channel

    response = type("Response", (), {
        "status_code": 200,
        "json": lambda _self: {"status": "sent", "message_id": "meta-ui:thread-1:123"},
    })()
    sent = {}
    monkeypatch.setattr(conversations, "_local_connector_thread_id", lambda *_args: "thread-1")
    monkeypatch.setattr(conversations, "decrypt_token", lambda *_args: "connector-token")
    monkeypatch.setattr(conversations.settings, setting_name, f"http://host.docker.internal:{port}")
    monkeypatch.setattr(conversations.httpx, "post", lambda url, **kwargs: (sent.update(url=url, **kwargs) or response))

    result, returned_channel = conversations.send_meta_text(
        db=TenantDb(),
        conversation={"id": 22, "channel_id": 11, "channel": channel_type},
        recipient_id="buyer-1",
        text_content="Chào bạn",
        business_id=7,
    )

    assert result["status"] == "sent"
    assert returned_channel is channel
    assert sent["url"] == f"http://host.docker.internal:{port}/send"
    assert sent["headers"]["X-Meta-Bridge-Secret"] == "connector-token"
    assert sent["json"] == {"threadId": "thread-1", "message": "Chào bạn", "recipientId": "buyer-1"}


def test_conversation_inbox_orders_preview_fields_by_each_message_timestamp():
    statements = []

    class QueryResult:
        def __init__(self, statement):
            self.statement = str(statement)

        def mappings(self):
            return self

        def all(self):
            return []

        def scalar_one(self):
            return 0

    class TenantDb:
        @staticmethod
        def execute(statement, _params):
            statements.append(str(statement))
            return QueryResult(statement)

    result = conversations.get_conversations(
        limit=None,
        offset=0,
        customer_id=None,
        unassigned_only=False,
        db=TenantDb(),
        tenant=type("Tenant", (), {"business_id": 4})(),
    )

    assert result["items"] == []
    inbox_sql = statements[0]
    assert inbox_sql.count("m.received_at DESC NULLS LAST") == 5
    assert "last_message_at DESC" in inbox_sql


def test_shopee_outbound_refuses_when_exact_thread_is_not_found(monkeypatch):
    actions = []

    class Page:
        @staticmethod
        def is_closed():
            return False

    monkeypatch.setattr(shopee_bot, "CONTROL_PAGE", Page())
    async def select_all(_page):
        actions.append("all")
        return True

    async def select_exact(_page, row):
        actions.append(row)
        return False

    monkeypatch.setattr(shopee_bot, "select_all_conversations_tab", select_all)
    monkeypatch.setattr(shopee_bot, "_select_shopee_conversation", select_exact)
    with pytest.raises(RuntimeError, match="danh sách Tất cả"):
        asyncio.run(shopee_bot.send_shopee_message("thread-1", "Chào bạn"))
    assert actions == ["all", {"threadId": "thread-1", "customerId": ""}]


def test_shopee_outbound_refuses_until_exact_thread_is_selected(monkeypatch):
    class Page:
        @staticmethod
        def is_closed():
            return False

        @staticmethod
        async def evaluate(_script, payload):
            assert payload["threadId"] == "thread-1"
            return {"found": True, "selected": False}

        @staticmethod
        async def wait_for_timeout(_milliseconds):
            pass

    monkeypatch.setattr(shopee_bot, "CONTROL_PAGE", Page())

    async def select_all(_page):
        return True

    async def select_exact(_page, _row):
        return False

    monkeypatch.setattr(shopee_bot, "select_all_conversations_tab", select_all)
    monkeypatch.setattr(shopee_bot, "_select_shopee_conversation", select_exact)
    with pytest.raises(RuntimeError, match="danh sách Tất cả"):
        asyncio.run(shopee_bot.send_shopee_message("thread-1", "Chào bạn"))


def test_shopee_selector_uses_the_app_handler_and_matches_selected_row():
    assert "[data-cy^=\"webchat-conversation-cell-root\"]" in shopee_bot.SHOPEE_CONVERSATION_JS
    assert "root[reactKey]?.onClick" in shopee_bot.SHOPEE_CONVERSATION_JS
    assert "webchat-conversation-cell-root-current" in shopee_bot.SHOPEE_CONVERSATION_JS
    assert ".click()" not in shopee_bot.SHOPEE_CONVERSATION_JS


def test_shopee_avatar_scripts_include_the_current_conversation(monkeypatch):
    class Page:
        async def evaluate(self, script, *_args):
            assert '[data-cy^="webchat-conversation-cell-root"]' in script
            if "externalUserId" in script:
                return [{"externalUserId": "buyer-1", "avatar": "//cdn.example/avatar.png"}]
            return "//cdn.example/avatar.png"

    posted = []
    monkeypatch.setattr(shopee_bot, "SYNCED_AVATAR_IDS", set())
    monkeypatch.setattr(shopee_bot, "post_profiles", lambda profiles: (
        posted.extend(profiles) or (200, '{"updated":1,"matchedExternalUserIds":["buyer-1"]}')
    ))
    asyncio.run(shopee_bot.sync_visible_avatars(Page()))
    avatar = asyncio.run(shopee_bot.enrich_avatar_from_edge(
        Page(), {"threadId": "thread-1", "authorId": "buyer-1"}
    ))

    assert posted == [{"externalUserId": "buyer-1", "avatarUrl": "https://cdn.example/avatar.png"}]
    assert avatar == "https://cdn.example/avatar.png"
    assert "buyer-1" in shopee_bot.SYNCED_AVATAR_IDS


def test_shopee_avatar_ids_are_not_cached_before_customer_exists(monkeypatch):
    class Page:
        async def evaluate(self, _script):
            return [{"externalUserId": "buyer-2", "avatar": "https://cdn.example/avatar.png"}]

    monkeypatch.setattr(shopee_bot, "SYNCED_AVATAR_IDS", set())
    monkeypatch.setattr(
        shopee_bot,
        "post_profiles",
        lambda _profiles: (200, '{"updated":0,"matchedExternalUserIds":[]}'),
    )

    asyncio.run(shopee_bot.sync_visible_avatars(Page()))

    assert "buyer-2" not in shopee_bot.SYNCED_AVATAR_IDS


def test_shopee_avatar_extractor_accepts_json_encoded_url_lists():
    assert shopee_bot.extract_avatar_url('{"url_list":["//cf.shopee.vn/file/avatar"]}') == (
        "https://cf.shopee.vn/file/avatar"
    )


def test_shopee_outbound_clicks_the_seller_chat_send_icon(monkeypatch):
    actions = []

    class Composer:
        async def fill(self, text):
            actions.append(("fill", text))

    class ComposerLocator:
        async def count(self):
            return 1

        def nth(self, _index):
            return Composer()

    class SendIcon:
        async def click(self):
            actions.append(("click", "send-icon"))

    class SendIconsLocator:
        async def evaluate_all(self, _script):
            return 3

        def nth(self, index):
            assert index == 3
            return SendIcon()

    class NoWarning:
        async def count(self):
            return 0

    class Page:
        visible_messages = 0

        @staticmethod
        def is_closed():
            return False

        @staticmethod
        async def evaluate(script, payload):
            if "threadId" in payload:
                return {"found": True, "selected": True}
            assert script == shopee_bot.SHOPEE_MESSAGE_COUNT_JS
            assert payload == "Xin chào"
            return Page.visible_messages

        @staticmethod
        async def wait_for_timeout(_milliseconds):
            pass

        @staticmethod
        def locator(selector):
            assert 'data-cy="webchat-conversation-detail-input"' in selector
            return ComposerLocator() if "textarea:visible" in selector else SendIconsLocator()

        @staticmethod
        async def wait_for_function(script, *, arg=None, timeout=0):
            assert timeout in (8000, 10000)
            if script == shopee_bot.SHOPEE_MESSAGE_APPEARED_JS:
                assert Page.visible_messages == 0
                assert arg == {"text": "Xin chào", "previousCount": 0}

        @staticmethod
        def get_by_text(_text, exact):
            assert exact is False
            return NoWarning()

    monkeypatch.setattr(shopee_bot, "CONTROL_PAGE", Page())
    async def select_all(_page):
        return True

    async def select_exact(_page, _row):
        return True

    monkeypatch.setattr(shopee_bot, "select_all_conversations_tab", select_all)
    monkeypatch.setattr(shopee_bot, "_select_shopee_conversation", select_exact)
    result = asyncio.run(shopee_bot.send_shopee_message("thread-1", "Xin chào"))

    assert result["status"] == "sent"
    assert actions == [("fill", "Xin chào"), ("click", "send-icon")]


def test_shopee_outbound_does_not_report_success_when_chat_does_not_acknowledge(monkeypatch):
    class Composer:
        async def fill(self, _text):
            pass

    class ComposerLocator:
        async def count(self):
            return 1

        def nth(self, _index):
            return Composer()

    class SendIcon:
        async def click(self):
            pass

    class SendIconsLocator:
        async def evaluate_all(self, _script):
            return 0

        def nth(self, _index):
            return SendIcon()

    class NoWarning:
        async def count(self):
            return 0

    class Page:
        @staticmethod
        def is_closed():
            return False

        @staticmethod
        async def evaluate(script, payload):
            if "threadId" in payload:
                return {"found": True, "selected": True}
            assert script == shopee_bot.SHOPEE_MESSAGE_COUNT_JS
            return 0

        @staticmethod
        async def wait_for_timeout(_milliseconds):
            pass

        @staticmethod
        async def wait_for_function(script, *, arg=None, timeout=0):
            if script == shopee_bot.SHOPEE_MESSAGE_APPEARED_JS:
                assert timeout == 10000
                assert arg == {"text": "Xin chào", "previousCount": 0}
                raise TimeoutError("message did not appear")

        @staticmethod
        def locator(selector):
            return ComposerLocator() if "textarea:visible" in selector else SendIconsLocator()

        @staticmethod
        def get_by_text(_text, exact):
            assert exact is False
            return NoWarning()

    monkeypatch.setattr(shopee_bot, "CONTROL_PAGE", Page())
    async def select_all(_page):
        return True

    async def select_exact(_page, _row):
        return True

    monkeypatch.setattr(shopee_bot, "select_all_conversations_tab", select_all)
    monkeypatch.setattr(shopee_bot, "_select_shopee_conversation", select_exact)
    with pytest.raises(shopee_bot.ShopeeDeliveryUnknown, match="trạng thái gửi chưa xác nhận"):
        asyncio.run(shopee_bot.send_shopee_message("thread-1", "Xin chào"))


def test_shopee_outbound_surfaces_platform_moderation_warning(monkeypatch):
    class Warning:
        async def count(self):
            return 1

        def nth(self, _index):
            return self

        async def is_visible(self):
            return True

    class Composer:
        async def fill(self, _text):
            pass

        async def click(self):
            pass

    class Locator:
        async def count(self):
            return 1

        def nth(self, _index):
            return Composer()

        async def evaluate_all(self, _script):
            return 0

    class Page:
        @staticmethod
        def is_closed():
            return False

        @staticmethod
        async def evaluate(_script, _payload):
            return {"found": True, "selected": True}

        @staticmethod
        async def wait_for_timeout(_milliseconds):
            pass

        @staticmethod
        def locator(_selector):
            return Locator()

        @staticmethod
        def get_by_text(_text, exact):
            assert exact is False
            return Warning()

    monkeypatch.setattr(shopee_bot, "CONTROL_PAGE", Page())
    async def select_all(_page):
        return True

    async def select_exact(_page, _row):
        return True

    monkeypatch.setattr(shopee_bot, "select_all_conversations_tab", select_all)
    monkeypatch.setattr(shopee_bot, "_select_shopee_conversation", select_exact)
    with pytest.raises(RuntimeError, match="Shopee cảnh báo phản hồi"):
        asyncio.run(shopee_bot.send_shopee_message("thread-1", "Trả lời"))


def test_shopee_edge_startup_waits_for_slow_debug_endpoint(tmp_path, monkeypatch):
    edge = tmp_path / "msedge.exe"
    edge.touch()
    calls = []
    probes = 0

    monkeypatch.setattr(shopee_bot, "find_edge", lambda: edge)
    monkeypatch.setattr(shopee_bot, "EDGE_PROFILE", tmp_path / "edge-profile")
    monkeypatch.setattr(shopee_bot.subprocess, "Popen", lambda args, **kwargs: calls.append(args))
    monkeypatch.setattr(shopee_bot.time, "sleep", lambda _: None)

    def ready_after_slow_start():
        nonlocal probes
        probes += 1
        return probes > 60

    monkeypatch.setattr(shopee_bot, "cdp_ready", ready_after_slow_start)

    shopee_bot.start_edge()

    assert probes == 61
    assert "--no-first-run" in calls[0]
    assert "--no-default-browser-check" in calls[0]


def test_shopee_connector_selects_visible_all_conversations_tab():
    actions = []
    selected = {"value": False}
    expanded = {"pre-sale": {"value": False}, "buyers": {"value": False}}

    class Tab:
        def __init__(self, kind, visible=True):
            self.kind = kind
            self.visible = visible

        async def is_visible(self):
            return self.visible

        async def evaluate(self, _script):
            if _script == shopee_bot.SHOPEE_ALL_BUYERS_EXPANDED_JS:
                return expanded[self.kind]["value"]
            return selected["value"]

        def locator(self, selector):
            assert selector == "xpath=.."
            return self

        async def click(self):
            if self.kind == "tab":
                actions.append("all")
                selected["value"] = True
            else:
                actions.append("pre-sale" if self.kind == "pre-sale" else "all buyers")
                expanded[self.kind]["value"] = True

    class Tabs:
        def __init__(self, items):
            self.items = items

        async def count(self):
            return len(self.items)

        def nth(self, index):
            return self.items[index]

    class Page:
        @staticmethod
        def get_by_text(text, exact):
            assert (text, exact) in {
                ("Tất cả cuộc trò chuyện", True),
                ("Khách hỏi chưa mua", False),
                ("Tất cả Người mua", True),
            }
            if text == "Tất cả cuộc trò chuyện":
                return Tabs([Tab("tab", False), Tab("tab")])
            return Tabs([Tab("pre-sale" if text == "Khách hỏi chưa mua" else "buyers")])

        @staticmethod
        async def wait_for_timeout(_milliseconds):
            pass

    assert asyncio.run(shopee_bot.select_all_conversations_tab(Page()))
    assert actions == ["all", "pre-sale", "all buyers"]


def test_shopee_optional_buyer_group_does_not_block_selected_all_tab():
    class Tab:
        async def is_visible(self):
            return True

        async def evaluate(self, script):
            if script == shopee_bot.SHOPEE_ALL_BUYERS_EXPANDED_JS:
                raise RuntimeError("Seller Chat markup changed")
            return True

        def locator(self, _selector):
            return self

        async def click(self):
            pass

    class Tabs:
        def __init__(self, items):
            self.items = items

        async def count(self):
            return len(self.items)

        def nth(self, index):
            return self.items[index]

    class Page:
        @staticmethod
        def get_by_text(text, exact):
            assert (text, exact) in {
                ("Tất cả cuộc trò chuyện", True),
                ("Khách hỏi chưa mua", False),
                ("Tất cả Người mua", True),
            }
            return Tabs([Tab()])

        @staticmethod
        async def wait_for_timeout(_milliseconds):
            pass

    assert asyncio.run(shopee_bot.select_all_conversations_tab(Page()))


def test_shopee_connector_does_not_claim_all_conversations_without_selection():
    class Tab:
        def __init__(self):
            self.selected = False

        async def is_visible(self):
            return True

        async def evaluate(self, _script):
            return self.selected

        def locator(self, _selector):
            return self

        async def click(self):
            pass

    class Tabs:
        async def count(self):
            return 1

        @staticmethod
        def nth(_index):
            return Tab()

    class Page:
        @staticmethod
        def get_by_text(_text, exact):
            assert exact is True
            return Tabs()

        @staticmethod
        async def wait_for_timeout(_milliseconds):
            pass

    assert not asyncio.run(shopee_bot.select_all_conversations_tab(Page()))


def test_shopee_history_uses_loaded_all_chat_rows_when_scroll_container_is_not_exposed(monkeypatch):
    row = {
        "id": "thread-1", "threadId": "thread-1", "customerId": "buyer-1",
        "displayName": "Buyer", "avatar": "https://cdn.example/avatar.png",
    }

    class Page:
        async def evaluate(self, script, *_args):
            if "webchat-conversation-cell-root" in script and "conversation.to_id" in script:
                return [row.copy()]
            if "direction" in script:
                return None
            return []

        @staticmethod
        async def wait_for_timeout(_milliseconds):
            pass

    monkeypatch.setattr(shopee_bot, "SHOPEE_CONVERSATION_SCAN_COMPLETE", True)
    rows = asyncio.run(shopee_bot._all_shopee_conversations(Page()))

    expected_row = {key: value for key, value in row.items() if key != "avatar"}
    expected_row["avatarUrl"] = "https://cdn.example/avatar.png"
    assert rows == [expected_row]
    assert not shopee_bot.SHOPEE_CONVERSATION_SCAN_COMPLETE


def test_shopee_conversation_scan_wheels_through_lazy_loaded_rows(monkeypatch):
    all_rows = [
        {
            "id": f"thread-{index}", "threadId": f"thread-{index}",
            "customerId": f"buyer-{index}", "displayName": f"Buyer {index}",
            "avatar": "",
        }
        for index in range(3)
    ]

    class Mouse:
        def __init__(self):
            self.position = 0

        async def move(self, _x, _y):
            pass

        async def wheel(self, _x, delta_y):
            assert delta_y > 0
            self.position = min(2, self.position + 1)

    class Page:
        def __init__(self):
            self.mouse = Mouse()

        async def evaluate(self, script, *_args):
            if "webchat-conversation-cell-root" in script and "conversation.to_id" in script:
                return [row.copy() for row in all_rows[:self.mouse.position + 1]]
            if "direction" in script:
                return None
            if "area =>" in script:
                return {"x": 20, "y": 20, "signature": str(self.mouse.position)}
            return None

        @staticmethod
        async def wait_for_timeout(_milliseconds):
            pass

    monkeypatch.setattr(shopee_bot, "SHOPEE_CONVERSATION_SCAN_COMPLETE", False)
    rows = asyncio.run(shopee_bot._all_shopee_conversations(Page()))

    assert [row["threadId"] for row in rows] == ["thread-0", "thread-1", "thread-2"]
    assert shopee_bot.SHOPEE_CONVERSATION_SCAN_COMPLETE


def test_shopee_history_returns_loaded_messages_when_scroll_area_is_not_exposed(monkeypatch):
    message = {"messageId": "message-1", "threadId": "thread-1", "content": "old message"}

    class Page:
        def __init__(self):
            self.history_capture = False

        async def evaluate(self, script, *_args):
            if "window.__SMH_SHOPEE_HISTORY_CAPTURE__ = true" in script:
                self.history_capture = True
                return None
            if "window.__SMH_SHOPEE_HISTORY_CAPTURE__ = false" in script:
                self.history_capture = False
                return None
            if "const list = document.querySelector('#message-virtualized-list')" in script:
                return None
            if "area =>" in script:
                return {"x": 10, "y": 10, "signature": "loaded"}
            return None

        async def wait_for_selector(self, *_args, **_kwargs):
            pass

        @staticmethod
        async def wait_for_timeout(_milliseconds):
            pass

    page = Page()

    async def select_conversation(_page, _row):
        # Seller Chat fetches its old messages as the conversation opens. The
        # history listener must already be armed before this action.
        assert shopee_bot.HISTORY_CAPTURE_ENABLED
        assert page.history_capture
        shopee_bot.HISTORY_CAPTURE_MESSAGES = {"message-1": message}
        return True

    monkeypatch.setattr(shopee_bot, "_select_shopee_conversation", select_conversation)
    row = {"threadId": "thread-1", "customerId": "buyer-1"}
    messages, complete = asyncio.run(shopee_bot._capture_shopee_history(page, row))

    assert messages == [message]
    assert not complete
    assert not shopee_bot.HISTORY_CAPTURE_ENABLED


def test_shopee_challenge_detector_reports_visible_verification():
    class Page:
        async def evaluate(self, _script):
            return True

    assert asyncio.run(shopee_bot._shopee_challenge_visible(Page()))


def test_shopee_cdp_ready_uses_fixed_port_without_active_port_file(tmp_path, monkeypatch):
    class EdgeResponse:
        status = 200

        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return self.body

    monkeypatch.setattr(shopee_bot, "EDGE_PROFILE", tmp_path)
    responses = {
        shopee_bot.CDP + "/json/version": EdgeResponse(b'{"Browser":"Edg/154.0.4258.48"}'),
        shopee_bot.CDP + "/json/list": EdgeResponse(b'[{"type":"page","url":"https://banhang.shopee.vn/new-webchat/conversations"}]'),
    }
    monkeypatch.setattr(shopee_bot, "urlopen", lambda url, **_kwargs: responses[url])

    assert not (tmp_path / "DevToolsActivePort").exists()
    assert shopee_bot.cdp_ready()

    responses[shopee_bot.CDP + "/json/list"] = EdgeResponse(b'[{"type":"page","url":"https://example.com/"}]')
    assert not shopee_bot.cdp_ready()
    assert shopee_bot.cdp_browser_ready()


def test_shopee_connector_recovers_when_debug_port_disappears(monkeypatch):
    events = []
    monkeypatch.setattr(shopee_bot, "cdp_browser_ready", lambda: False)
    monkeypatch.setattr(shopee_bot, "start_edge", lambda: events.append("restart"))

    shopee_bot.ensure_edge_connection()

    assert events == ["restart"]


def test_shopee_connector_reuses_edge_if_only_seller_tab_closed(monkeypatch):
    monkeypatch.setattr(shopee_bot, "cdp_browser_ready", lambda: True)
    monkeypatch.setattr(shopee_bot, "start_edge", lambda: pytest.fail("must reuse Edge"))

    shopee_bot.ensure_edge_connection()


def test_shopee_waits_for_selected_chat_messages_to_render():
    attempts = []

    class Page:
        async def evaluate(self, script, text):
            assert script == shopee_bot.SHOPEE_MESSAGE_COUNT_JS
            assert text == "Xin chào"
            attempts.append("check")
            return None if attempts.count("check") < 3 else 0

        async def wait_for_timeout(self, milliseconds):
            assert milliseconds == 250
            attempts.append("wait")

    assert asyncio.run(shopee_bot.wait_for_message_list(Page(), "Xin chào")) == 0
    assert attempts == ["check", "wait", "check", "wait", "check"]


def test_shopee_message_acknowledgement_supports_current_seller_chat_container():
    selector = '[data-cy="webchat-conversation-detail-message-container"]'
    assert selector in shopee_bot.SHOPEE_MESSAGE_COUNT_JS
    assert selector in shopee_bot.SHOPEE_MESSAGE_APPEARED_JS
    for script in (shopee_bot.SHOPEE_MESSAGE_COUNT_JS, shopee_bot.SHOPEE_MESSAGE_APPEARED_JS):
        assert '[data-cy="webchat-message-send"] pre > div' in script
        assert "Node.TEXT_NODE" in script


def test_shopee_does_not_post_same_inflight_message_twice(monkeypatch):
    calls = []
    release = asyncio.Event()

    async def slow_post(_function, message):
        calls.append(message["messageId"])
        await release.wait()
        return 200, "{}"

    monkeypatch.setattr(shopee_bot, "SEEN_MESSAGE_IDS", {})
    monkeypatch.setattr(shopee_bot, "IN_FLIGHT_MESSAGE_IDS", set())
    monkeypatch.setattr(shopee_bot.asyncio, "to_thread", slow_post)

    async def check():
        message = {"messageId": "duplicate-1"}
        first = asyncio.create_task(shopee_bot.deliver(message))
        await asyncio.sleep(0)
        await shopee_bot.deliver(message)
        release.set()
        await first

    asyncio.run(check())
    assert calls == ["duplicate-1"]
