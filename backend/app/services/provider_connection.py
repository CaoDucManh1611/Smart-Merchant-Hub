"""Provider-side validation and webhook setup for self-service channels."""

from __future__ import annotations

from typing import Any

import httpx

from app.rag.run_logger import safe_error_message


TELEGRAM_API_BASE = "https://api.telegram.org/bot"
ZALO_API_BASE = "https://bot-api.zaloplatforms.com/bot"


class ProviderConnectionError(ValueError):
    """An actionable provider connection failure safe to show to a shop admin."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _post_json(url: str, *, json: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        response = httpx.post(url, json=json or {}, timeout=15)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderConnectionError(
            "provider_unreachable",
            "Không thể kết nối tới nhà cung cấp. Hãy thử lại sau.",
        ) from exc
    if not isinstance(body, dict):
        raise ProviderConnectionError(
            "invalid_provider_response",
            "Nhà cung cấp trả về dữ liệu không hợp lệ. Hãy thử lại.",
        )
    # Telegram Bot API uses ``ok: true`` while Zalo Bot/OA bridges may expose
    # the same successful payload as ``error: 0`` with a ``data`` object. Keep
    # both official response shapes compatible without relaxing validation for
    # an empty or malformed response.
    success = body.get("ok") is True or body.get("error") in (0, "0")
    if not success:
        detail = body.get("description") or body.get("message") if isinstance(body, dict) else None
        safe_detail = safe_error_message(detail, limit=300) if detail else ""
        raise ProviderConnectionError(
            "invalid_provider_response",
            safe_detail or "Token không hợp lệ hoặc nhà cung cấp từ chối yêu cầu.",
        )
    return body


def _result(body: dict[str, Any]) -> dict[str, Any]:
    """Read the provider payload from Telegram and Zalo response envelopes."""

    value = body.get("result")
    if isinstance(value, dict):
        return value
    value = body.get("data")
    return value if isinstance(value, dict) else {}


def _webhook_info(channel_type: str, access_token: str) -> dict[str, Any]:
    base = TELEGRAM_API_BASE if channel_type == "telegram" else ZALO_API_BASE
    return _result(_post_json(f"{base}{access_token}/getWebhookInfo"))


def verify_and_configure_bot(
    *,
    channel_type: str,
    access_token: str,
    webhook_url: str,
    webhook_secret: str,
) -> dict[str, Any]:
    """Validate a Bot Creator/BotFather token and configure its webhook.

    The provider token is only used in-memory for these calls. Callers are
    responsible for encrypting it before persistence.
    """

    channel_type = str(channel_type or "").strip().lower()
    access_token = str(access_token or "").strip()
    if channel_type not in {"telegram", "zalo"}:
        raise ProviderConnectionError("unsupported_channel", "Kênh này chưa hỗ trợ kết nối tự động.")
    if not access_token:
        raise ProviderConnectionError("missing_token", "Bạn cần nhập Bot Token.")
    if not webhook_url.lower().startswith("https://"):
        raise ProviderConnectionError("webhook_requires_https", "Webhook phải dùng URL HTTPS công khai.")

    base = TELEGRAM_API_BASE if channel_type == "telegram" else ZALO_API_BASE
    identity_body = _post_json(f"{base}{access_token}/getMe")
    identity = _result(identity_body)
    if not isinstance(identity, dict) or not identity.get("id"):
        raise ProviderConnectionError("invalid_bot_identity", "Token không trả về thông tin bot hợp lệ.")
    if channel_type == "telegram" and identity.get("is_bot") is False:
        raise ProviderConnectionError("invalid_bot_identity", "Token Telegram không thuộc về một bot.")

    if channel_type == "telegram":
        name = str(identity.get("first_name") or identity.get("username") or identity["id"]).strip()
        username = str(identity.get("username") or "").strip() or None
        webhook_payload: dict[str, Any] = {
            "url": webhook_url,
            "secret_token": webhook_secret,
            "allowed_updates": ["message", "edited_message", "callback_query"],
        }
    else:
        name = str(identity.get("account_name") or identity.get("name") or identity["id"]).strip()
        username = None
        webhook_payload = {"url": webhook_url, "secret_token": webhook_secret}

    set_body = _post_json(f"{base}{access_token}/setWebhook", json=webhook_payload)
    webhook_result = _result(set_body)
    info = _webhook_info(channel_type, access_token)
    configured_url = str(info.get("url") or webhook_result.get("url") or "").strip()
    if configured_url != webhook_url:
        raise ProviderConnectionError(
            "webhook_not_confirmed",
            "Đã xác minh bot nhưng chưa xác nhận được webhook. Hãy kiểm tra URL công khai rồi thử lại.",
        )
    return {
        "external_account_id": str(identity["id"]),
        "name": name[:255],
        "username": username,
        "provider_account": {
            "id": str(identity["id"]),
            "name": name[:255],
            **({"username": username} if username else {}),
        },
        "webhook_status": "connected",
        "webhook_url": webhook_url,
    }
