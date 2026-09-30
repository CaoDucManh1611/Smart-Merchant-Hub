import sys
from pathlib import Path

import pytest


_SCRIPTS = Path(__file__).parents[2] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
from tiktok_bot import CONTROL_CODE, _parse_cookie_input, install_plugin


def test_parses_cookie_header():
    assert _parse_cookie_input("Cookie: sessionid=abc; msToken=xyz") == {
        "sessionid": "abc",
        "msToken": "xyz",
    }


def test_parses_tiktok_json_and_ignores_other_domains():
    cookies = _parse_cookie_input(
        '[{"name":"sessionid","value":"abc","domain":".tiktok.com"},'
        '{"name":"sid","value":"unrelated","domain":"example.com"}]'
    )
    assert cookies == {"sessionid": "abc"}


def test_rejects_cookie_without_tiktok_session():
    with pytest.raises(ValueError, match="sessionid"):
        _parse_cookie_input("ttwid=abc")


def test_tiktok_outbound_auth_reads_secret_without_global_lookup():
    assert 'os.getenv("TIKTOK_BRIDGE_SECRET") or os.getenv("TIKTOK_CONNECTOR_TOKEN")' in CONTROL_CODE
    assert "if not BRIDGE_SECRET" not in CONTROL_CODE
    assert 'TIKTOK_BRIDGE_CONTROL_HOST", "0.0.0.0"' in CONTROL_CODE


def test_generated_tiktok_plugin_uses_crm_rag_reply_and_local_bridge_auth(tmp_path):
    plugin = tmp_path / "smart_merchant_bridge.py"
    plugin.write_text(
        'if not BRIDGE_SECRET or not _hmac.compare_digest(str(provided), str(BRIDGE_SECRET)):\n',
        encoding="utf-8",
    )
    install_plugin(plugin)
    source = plugin.read_text(encoding="utf-8")

    assert 'os.getenv("TIKTOK_BRIDGE_SECRET") or os.getenv("TIKTOK_CONNECTOR_TOKEN")' in source
    assert "if not BRIDGE_SECRET" not in source
    assert "TIKTOK_AUTO_REPLY" not in source
    assert "bot.send_message(text=reply" not in source
    assert "CRM xử lý RAG và gửi trả lời qua bridge" in source
