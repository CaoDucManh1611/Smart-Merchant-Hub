import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.responses import FileResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import shopee_bot
from shopee_bot import normalize_message

from app.api import local_connectors
from app.api.local_connectors import _code_parts, download_local_connector_app, download_local_connector_bundle_legacy


@pytest.mark.parametrize("channel", ["tiktok", "shopee"])
def test_pairing_and_connector_codes_are_shop_scoped(channel):
    code = f"PAIR.{channel}.12.34.abcdEFGHijkl_1234"
    assert _code_parts(code, "PAIR") == (channel, 12, 34, "abcdEFGHijkl_1234")

    token = f"CONN.{channel}.12.34.abcdEFGHijkl_1234"
    assert _code_parts(token, "CONN", channel) == (channel, 12, 34, "abcdEFGHijkl_1234")


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
