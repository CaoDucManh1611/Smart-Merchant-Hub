"""MFA enrollment preparation without exposing persisted secrets."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from datetime import datetime, timezone
from urllib.parse import quote

from app.core.config import settings
from app.models.business import User
from app.services.channel_credentials import decrypt_token, encrypt_token


def _encryption_key() -> str:
    return settings.CHANNEL_ENCRYPTION_KEY or settings.AUTH_SECRET or settings.APP_NAME


def prepare_mfa(user: User) -> str:
    secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
    user.mfa_secret_encrypted = encrypt_token(secret, _encryption_key())
    user.mfa_status = "prepared"
    user.mfa_prepared_at = datetime.now(timezone.utc).replace(tzinfo=None)
    label = quote(f"Smart Merchant Hub:{user.email}")
    issuer = quote("Smart Merchant Hub")
    return f"otpauth://totp/{label}?secret={secret}&issuer={issuer}"


def disable_mfa(user: User) -> None:
    user.mfa_secret_encrypted = None
    user.mfa_status = "disabled"
    user.mfa_prepared_at = None


def verify_mfa_code(user: User, code: str, *, timestamp: int | None = None) -> bool:
    """Verify a RFC 6238 six-digit code with a small clock-skew window."""
    if user.mfa_status not in {"prepared", "enabled"} or not user.mfa_secret_encrypted:
        return False
    try:
        secret = decrypt_token(user.mfa_secret_encrypted, _encryption_key())
        raw_secret = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8), casefold=True)
    except (TypeError, ValueError):
        return False
    now = int(datetime.now(timezone.utc).timestamp() if timestamp is None else timestamp)
    supplied = str(code or "").strip()
    if len(supplied) != 6 or not supplied.isdigit():
        return False
    for offset in (-1, 0, 1):
        counter = (now // 30) + offset
        digest = hmac.new(raw_secret, struct.pack(">Q", counter), hashlib.sha1).digest()
        index = digest[-1] & 0x0F
        value = (struct.unpack(">I", digest[index:index + 4])[0] & 0x7FFFFFFF) % 1_000_000
        if hmac.compare_digest(f"{value:06d}", supplied):
            return True
    return False


def enable_mfa(user: User) -> None:
    user.mfa_status = "enabled"
    user.mfa_prepared_at = user.mfa_prepared_at or datetime.now(timezone.utc).replace(tzinfo=None)
