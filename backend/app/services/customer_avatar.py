"""Signed customer avatar URLs and provider-backed avatar retrieval."""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from app.core.config import settings


CUSTOMER_AVATAR_TTL_SECONDS = 15 * 60
PROVIDER_PROXY_CHANNELS = frozenset({"facebook", "instagram", "telegram", "zalo", "tiktok", "shopee"})
MARKETPLACE_AVATAR_HOSTS = {
    "tiktok": (
        "tiktokcdn.com",
        "tiktokcdn-us.com",
        "tiktokcdn-eu.com",
        "tiktokv.com",
        "byteoversea.com",
        "ibytedtos.com",
        "byteimg.com",
    ),
    "shopee": ("susercontent.com", "shopee.vn"),
}
META_AVATAR_HOSTS = (
    "fbcdn.net",
    "cdninstagram.com",
    "fbsbx.com",
    "lookaside.instagram.com",
)


def is_trusted_meta_avatar_url(value: object) -> bool:
    """Return whether a URL is an HTTPS image URL hosted by Meta's CDNs."""
    text = str(value or "").strip()
    if not text:
        return False
    try:
        parsed = urlsplit(text)
        hostname = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    if parsed.scheme.lower() != "https" or not hostname:
        return False
    return any(
        hostname == host or hostname.endswith(f".{host}")
        for host in META_AVATAR_HOSTS
    )


def marketplace_avatar_channel(value: object) -> str | None:
    """Identify HTTPS avatar URLs served by TikTok or Shopee CDNs."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = urlsplit(text)
        hostname = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    if parsed.scheme.lower() != "https" or not hostname:
        return None
    for channel, hosts in MARKETPLACE_AVATAR_HOSTS.items():
        if any(hostname == host or hostname.endswith(f".{host}") for host in hosts):
            return channel
    return None


def is_trusted_marketplace_avatar_url(value: object, channel: str | None = None) -> bool:
    detected_channel = marketplace_avatar_channel(value)
    return detected_channel is not None and (
        not channel or detected_channel == str(channel).strip().lower()
    )


def _signing_secret() -> bytes:
    configured = str(settings.CHANNEL_ENCRYPTION_KEY or "").strip()
    return (configured or f"{settings.APP_NAME}:customer-avatar-url").encode("utf-8")


def _signature(
    *, customer_id: int, business_id: int, expires: int, channel: str | None = None
) -> str:
    payload = f"{int(customer_id)}:{int(business_id)}:{int(expires)}".encode("utf-8")
    if channel:
        payload += f":{channel}".encode("utf-8")
    return hmac.new(_signing_secret(), payload, hashlib.sha256).hexdigest()


def build_customer_avatar_url(
    *,
    customer_id: int,
    business_id: int,
    ttl_seconds: int = CUSTOMER_AVATAR_TTL_SECONDS,
    base_url: str | None = None,
    channel: str | None = None,
) -> str:
    """Build an expiring URL that browser image tags can load without headers."""
    expires = int(time.time()) + max(1, int(ttl_seconds))
    channel = str(channel or "").strip().lower()
    channel = channel if channel in PROVIDER_PROXY_CHANNELS else None
    signature = _signature(
        customer_id=customer_id,
        business_id=business_id,
        expires=expires,
        channel=channel,
    )
    base = str(
        base_url
        if base_url is not None
        else settings.PUBLIC_BASE_URL
    ).strip().rstrip("/")
    # Older local .env files sometimes put the Meta OAuth callback URL in
    # PUBLIC_BASE_URL.  Keep avatar URLs valid by retaining only the public
    # origin when that legacy value is encountered.
    if "/api/" in base:
        base = base.split("/api/", 1)[0].rstrip("/")
    # Local development normally leaves PUBLIC_BASE_URL empty.  Keep the URL
    # absolute because the SPA runs on :5173 while the API runs on :8000.
    base = base or "http://127.0.0.1:8000"
    params = {"business_id": int(business_id), "expires": expires, "signature": signature}
    if channel:
        params["channel"] = channel
    query = urlencode(params)
    return f"{base}/api/customers/{int(customer_id)}/avatar?{query}"


def refresh_customer_avatar_url(
    value: object,
    *,
    customer_id: int,
    business_id: int,
    channel: str | None = None,
    base_url: str | None = None,
) -> str | None:
    """Re-issue a stored signed avatar URL before returning it to a client.

    Telegram avatar URLs are deliberately short-lived so a bot token never
    reaches the browser. The customer row may therefore contain an expired
    URL even though the provider-backed photo is still available. Only URLs
    belonging to our avatar proxy are refreshed; external provider URLs are
    returned unchanged.
    """
    text = str(value or "").strip()
    parsed = None
    if text:
        try:
            parsed = urlsplit(text)
        except ValueError:
            return text
    expected_path = f"/api/customers/{int(customer_id)}/avatar"
    if parsed and parsed.path.rstrip("/") == expected_path:
        stored_channel = parse_qs(parsed.query).get("channel", [""])[0].strip().lower()
        source_channel = stored_channel if stored_channel in PROVIDER_PROXY_CHANNELS else None
        source_channel = source_channel or (
            str(channel or "").strip().lower()
            if str(channel or "").strip().lower() in PROVIDER_PROXY_CHANNELS
            else None
        )
        return build_customer_avatar_url(
            customer_id=customer_id,
            business_id=business_id,
            base_url=base_url,
            channel=source_channel,
        )

    marketplace_channel = marketplace_avatar_channel(text)
    if marketplace_channel:
        return build_customer_avatar_url(
            customer_id=customer_id,
            business_id=business_id,
            base_url=base_url,
            channel=marketplace_channel,
        )

    source_channel = str(channel or "").strip().lower()
    if source_channel in PROVIDER_PROXY_CHANNELS:
        return build_customer_avatar_url(
            customer_id=customer_id,
            business_id=business_id,
            base_url=base_url,
            channel=source_channel,
        )
    if not text:
        return None

    return build_customer_avatar_url(
        customer_id=customer_id,
        business_id=business_id,
        base_url=base_url,
    )


def verify_customer_avatar_url(
    *,
    customer_id: int,
    business_id: int,
    expires: int,
    signature: str,
    channel: str | None = None,
) -> bool:
    """Verify both expiry and tenant/customer binding of a signed URL."""
    try:
        if int(expires) < int(time.time()):
            return False
    except (TypeError, ValueError):
        return False
    expected = _signature(
        customer_id=customer_id,
        business_id=business_id,
        expires=int(expires),
        channel=(str(channel or "").strip().lower() or None),
    )
    return hmac.compare_digest(str(signature or ""), expected)
