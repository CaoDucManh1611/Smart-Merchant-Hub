"""MFA enrollment preparation without exposing persisted secrets."""

from __future__ import annotations

import base64
import secrets
from datetime import datetime, timezone
from urllib.parse import quote

from app.core.config import settings
from app.models.business import User
from app.services.channel_credentials import encrypt_token


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
