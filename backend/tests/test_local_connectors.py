import asyncio
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.responses import FileResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import shopee_bot
import connector_pairing
from shopee_bot import normalize_message

from app.api import conversations, local_connectors, onboarding
from app.api.local_connectors import _code_parts, download_local_connector_app, download_local_connector_bundle_legacy


@pytest.mark.parametrize("channel", ["tiktok", "shopee"])
def test_pairing_and_connector_codes_are_shop_scoped(channel):
    code = f"PAIR.{channel}.12.34.abcdEFGHijkl_1234"
    assert _code_parts(code, "PAIR") == (channel, 12, 34, "abcdEFGHijkl_1234")

    token = f"CONN.{channel}.12.34.abcdEFGHijkl_1234"
    assert _code_parts(token, "CONN", channel) == (channel, 12, 34, "abcdEFGHijkl_1234")


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
    [("tiktok", "SmartMerchantTikTok.exe"), ("shopee", "SmartMerchantShopee.exe")],
)
def test_connector_download_serves_the_executable(channel, filename, tmp_path, monkeypatch):
    executable = tmp_path / filename
    executable.write_bytes(b"MZ" + b"0" * (1024 * 1024))
    monkeypatch.setattr(local_connectors, "_connector_exe_path", lambda _: executable)

    response = download_local_connector_app(channel)

    assert isinstance(response, FileResponse)
    assert response.path == executable
    assert response.media_type == "application/vnd.microsoft.portable-executable"
    assert response.filename == filename
    assert filename in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "no-store"


def test_connector_download_reports_missing_executable(monkeypatch):
    monkeypatch.setattr(local_connectors, "_connector_exe_path", lambda _: None)

    with pytest.raises(HTTPException) as missing:
        download_local_connector_app("shopee")

    assert missing.value.status_code == 503


def test_old_zip_download_route_returns_gone():
    with pytest.raises(HTTPException) as removed:
        download_local_connector_bundle_legacy("tiktok")

    assert removed.value.status_code == 410


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


def test_shopee_avatar_sync_only_fills_avatar_for_existing_shop_customer(monkeypatch):
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

    monkeypatch.setattr(local_connectors, "_connector_channel", lambda *_args: (7, 11))
    monkeypatch.setattr(local_connectors, "_tenant_schema", lambda *_args: "tenant_7")
    monkeypatch.setattr(local_connectors, "tenant_session", tenant_session)

    result = local_connectors.sync_shopee_customer_avatars(
        {"profiles": [{"externalUserId": "buyer-1", "avatarUrl": "https://cf.shopee.vn/file/buyer"}]},
        "Bearer connector-token",
        object(),
    )

    assert result == {"status": "synced", "updated": 1}
    assert customer.avatar_url == "https://cf.shopee.vn/file/buyer"


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


def test_shopee_outbound_refuses_when_exact_thread_is_not_found(monkeypatch):
    class Page:
        @staticmethod
        def is_closed():
            return False

        @staticmethod
        async def evaluate(_script, _thread_id):
            return False

    monkeypatch.setattr(shopee_bot, "CONTROL_PAGE", Page())
    with pytest.raises(RuntimeError, match="chưa được tải"):
        asyncio.run(shopee_bot.send_shopee_message("thread-1", "Chào bạn"))


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
    with pytest.raises(RuntimeError, match="chưa xác nhận"):
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
    monkeypatch.setattr(shopee_bot, "post_profiles", lambda profiles: (posted.extend(profiles) or (200, '{"updated":1}')))
    asyncio.run(shopee_bot.sync_visible_avatars(Page()))
    avatar = asyncio.run(shopee_bot.enrich_avatar_from_edge(
        Page(), {"threadId": "thread-1", "authorId": "buyer-1"}
    ))

    assert posted == [{"externalUserId": "buyer-1", "avatarUrl": "https://cdn.example/avatar.png"}]
    assert avatar == "https://cdn.example/avatar.png"


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
        def locator(selector):
            assert 'data-cy="webchat-conversation-detail-input"' in selector
            return ComposerLocator() if "textarea:visible" in selector else SendIconsLocator()

        @staticmethod
        async def wait_for_function(_script, timeout):
            assert timeout == 8000

        @staticmethod
        def get_by_text(_text, exact):
            assert exact is False
            return NoWarning()

    monkeypatch.setattr(shopee_bot, "CONTROL_PAGE", Page())
    result = asyncio.run(shopee_bot.send_shopee_message("thread-1", "Xin chào"))

    assert result["status"] == "sent"
    assert actions == [("fill", "Xin chào"), ("click", "send-icon")]


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
    buyers_expanded = {"value": False}

    class Tab:
        def __init__(self, kind, visible=True):
            self.kind = kind
            self.visible = visible

        async def is_visible(self):
            return self.visible

        async def evaluate(self, _script):
            if _script == shopee_bot.SHOPEE_ALL_BUYERS_EXPANDED_JS:
                return buyers_expanded["value"]
            return selected["value"]

        def locator(self, selector):
            assert selector == "xpath=.."
            return self

        async def click(self):
            if self.kind == "tab":
                actions.append("all")
                selected["value"] = True
            else:
                actions.append("all buyers")
                buyers_expanded["value"] = True

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
            assert exact is True
            assert text in {"Tất cả cuộc trò chuyện", "Tất cả Người mua"}
            if text == "Tất cả cuộc trò chuyện":
                return Tabs([Tab("tab", False), Tab("tab")])
            return Tabs([Tab("buyers")])

        @staticmethod
        async def wait_for_timeout(_milliseconds):
            pass

    assert asyncio.run(shopee_bot.select_all_conversations_tab(Page()))
    assert actions == ["all", "all buyers"]


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
