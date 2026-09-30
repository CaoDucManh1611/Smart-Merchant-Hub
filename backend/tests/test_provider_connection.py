from unittest.mock import Mock, patch

import pytest

from app.services.provider_connection import ProviderConnectionError, verify_and_configure_bot


def test_provider_http_error_preserves_sanitized_provider_reason():
    response = Mock(status_code=400)
    response.json.return_value = {
        "ok": False,
        "description": "Bad Request: bad webhook: invalid certificate",
    }

    with patch("httpx.post", return_value=response), pytest.raises(ProviderConnectionError) as raised:
        verify_and_configure_bot(
            channel_type="telegram",
            access_token="12345:secret-token",
            webhook_url="https://crm.example.test/api/webhooks/telegram",
            webhook_secret="webhook-secret",
        )

    assert raised.value.code == "provider_rejected"
    assert "invalid certificate" in raised.value.message


def test_telegram_token_with_bot_prefix_is_normalized_before_provider_call():
    calls = []

    class FakeResponse:
        status_code = 200

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

        def raise_for_status(self):
            return None

    def fake_post(url, **kwargs):
        calls.append(url)
        if url.endswith("/getMe"):
            return FakeResponse({"ok": True, "result": {"id": 42, "first_name": "Demo", "is_bot": True}})
        if url.endswith("/setWebhook"):
            return FakeResponse({"ok": True, "result": {"url": kwargs["json"]["url"]}})
        return FakeResponse({"ok": True, "result": {"url": "https://crm.example.test/api/webhooks/telegram"}})

    with patch("httpx.post", side_effect=fake_post):
        verify_and_configure_bot(
            channel_type="telegram",
            access_token="bot12345:secret-token",
            webhook_url="https://crm.example.test/api/webhooks/telegram",
            webhook_secret="webhook-secret",
        )

    assert calls[0] == "https://api.telegram.org/bot12345:secret-token/getMe"
