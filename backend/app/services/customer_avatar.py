"""Signed customer avatar URLs and provider-backed avatar retrieval."""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode, urlsplit

from app.core.config import settings


CUSTOMER_AVATAR_TTL_SECONDS = 15 * 60


def _signing_secret() -> bytes:
    configured = str(settings.CHANNEL_ENCRYPTION_KEY or "").strip()
    return (configured or f"{settings.APP_NAME}:customer-avatar-url").encode("utf-8")


def _signature(*, customer_id: int, business_id: int, expires: int) -> str:
    payload = f"{int(customer_id)}:{int(business_id)}:{int(expires)}".encode("utf-8")
    return hmac.new(_signing_secret(), payload, hashlib.sha256).hexdigest()


def build_customer_avatar_url(
    *,
    customer_id: int,
    business_id: int,
    ttl_seconds: int = CUSTOMER_AVATAR_TTL_SECONDS,
    base_url: str | None = None,
) -> str:
    """Build an expiring URL that browser image tags can load without headers."""
    expires = int(time.time()) + max(1, int(ttl_seconds))
    signature = _signature(
        customer_id=customer_id,
        business_id=business_id,
        expires=expires,
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
    query = urlencode(
        {
            "business_id": int(business_id),
            "expires": expires,
            "signature": signature,
        }
    )
    return f"{base}/api/customers/{int(customer_id)}/avatar?{query}"


def refresh_customer_avatar_url(
    value: object,
    *,
    customer_id: int,
    business_id: int,
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
    if not text:
        return None

    try:
        parsed = urlsplit(text)
    except ValueError:
        return text
    expected_path = f"/api/customers/{int(customer_id)}/avatar"
    if parsed.path.rstrip("/") != expected_path:
        return text

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
    )
    return hmac.compare_digest(str(signature or ""), expected)
