"""Webhook authenticity and channel-account tenant resolution."""

import hashlib
import hmac

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.channel import Channel
from app.core.config import settings
from app.services.channel_credentials import decrypt_token
from app.tenancy.registry import resolve_webhook_route


def _channel_webhook_secret(channel: Channel) -> str:
    """Read a channel secret whether legacy plaintext or encrypted config."""

    config = channel.config if isinstance(channel.config, dict) else {}
    plaintext = config.get("webhook_secret")
    if plaintext:
        return str(plaintext)
    encrypted = config.get("webhook_secret_encrypted")
    if encrypted and settings.CHANNEL_ENCRYPTION_KEY:
        try:
            return decrypt_token(str(encrypted), settings.CHANNEL_ENCRYPTION_KEY)
        except (ValueError, TypeError):
            return ""
    return ""


def verify_zalo_oa_signature(
    raw_body: bytes,
    *,
    signature: str | None,
    app_id: str | None,
    timestamp: str | None,
    oa_secret_key: str | None,
) -> bool:
    """Verify Zalo OA's ``X-ZEvent-Signature`` header.

    Zalo signs the application id, the exact JSON body, the event timestamp
    and the OA secret key with SHA-256.  The provider documents the header as
    ``mac=<hex digest>``; accepting surrounding whitespace keeps the parser
    tolerant without weakening the comparison.
    """
    if not signature or not app_id or not timestamp or not oa_secret_key:
        return False
    provided = signature.strip()
    if "=" in provided:
        prefix, provided = provided.split("=", 1)
        if prefix.strip().lower() != "mac":
            return False
    provided = provided.strip().lower()
    if len(provided) != 64:
        return False
    try:
        int(provided, 16)
    except ValueError:
        return False
    expected = hashlib.sha256(
        str(app_id).encode()
        + raw_body
        + str(timestamp).encode()
        + str(oa_secret_key).encode()
    ).hexdigest()
    return hmac.compare_digest(provided, expected)


def verify_meta_signature(raw_body: bytes, signature: str | None, app_secret: str) -> bool:
    if not signature or not signature.startswith("sha256=") or not app_secret:
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature[7:], expected)


def verify_tiktok_webhook_signature(
    raw_body: bytes,
    *,
    authorization: str | None,
    app_key: str | None,
    app_secret: str | None,
) -> bool:
    """Verify TikTok Shop's incoming webhook Authorization signature."""
    if not authorization or not app_key or not app_secret:
        return False
    provided = authorization.strip().lower()
    if len(provided) != 64:
        return False
    try:
        int(provided, 16)
    except ValueError:
        return False
    expected = hmac.new(
        app_secret.encode("utf-8"),
        str(app_key).encode("utf-8") + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(provided, expected)


def resolve_channel_business(
    db: Session,
    channel_type: str,
    external_account_id: str | None,
) -> int | None:
    if not external_account_id:
        return None
    try:
        return db.scalar(
            select(Channel.business_id).where(
                Channel.channel_type == channel_type,
                Channel.external_account_id == str(external_account_id),
                Channel.status == "active",
            )
        )
    except OperationalError:
        # Legacy development databases may not have channel tables yet.
        db.rollback()
        return None


def resolve_active_channel(
    db: Session,
    channel_type: str,
    external_account_id: str | None,
) -> Channel | None:
    """Resolve the complete active channel binding for legacy webhook paths."""
    if not external_account_id:
        return None
    try:
        return db.scalar(
            select(Channel).where(
                Channel.channel_type == channel_type,
                Channel.external_account_id == str(external_account_id),
                Channel.status == "active",
            )
        )
    except OperationalError:
        db.rollback()
        return None


def resolve_telegram_channel(
    platform_db: Session,
    secret_token: str | None,
    tenant_db: Session | None = None,
) -> Channel | None:
    """Resolve a Telegram webhook to its tenant-owned Channel.

    Telegram does not include the bot identity in an update. The secret
    header is therefore matched against the per-channel webhook secret; no
    global/default channel fallback is allowed.
    """
    if not secret_token:
        return None
    if tenant_db is not None:
        route = resolve_webhook_route(platform_db, "telegram", secret_token)
        if route is None:
            return None
        channel = tenant_db.get(Channel, route.channel_id)
        if channel is None or channel.status != "active" or channel.channel_type != "telegram":
            return None
        return channel
    # Compatibility is limited to local development databases. Production
    # must always resolve through the platform route registry.
    if settings.ENVIRONMENT.strip().lower() == "production":
        return None
    try:
        channels = platform_db.scalars(select(Channel).where(Channel.channel_type == "telegram", Channel.status == "active")).all()
    except OperationalError:
        platform_db.rollback()
        return None
    matches = [channel for channel in channels if hmac.compare_digest(_channel_webhook_secret(channel), secret_token)]
    return matches[0] if len(matches) == 1 else None


def resolve_zalo_channel(
    platform_db: Session,
    secret_token: str | None,
    tenant_db: Session | None = None,
) -> Channel | None:
    """Resolve a Zalo Bot webhook to its tenant-owned Channel.

    Zalo identifies the connection with the secret header, so the value is
    matched only against active ``zalo`` channels.  Ambiguous secrets are
    rejected instead of guessing a tenant.
    """
    if not secret_token:
        return None
    if tenant_db is not None:
        route = resolve_webhook_route(platform_db, "zalo", secret_token)
        if route is None:
            return None
        channel = tenant_db.get(Channel, route.channel_id)
        if channel is None or channel.status != "active" or channel.channel_type != "zalo":
            return None
        return channel
    if settings.ENVIRONMENT.strip().lower() == "production":
        return None
    try:
        channels = platform_db.scalars(select(Channel).where(Channel.channel_type == "zalo", Channel.status == "active")).all()
    except OperationalError:
        platform_db.rollback()
        return None
    matches = [channel for channel in channels if hmac.compare_digest(_channel_webhook_secret(channel), secret_token)]
    return matches[0] if len(matches) == 1 else None


def resolve_zalo_oa_channel(
    platform_db: Session,
    payload: dict,
    tenant_db: Session | None = None,
) -> Channel | None:
    """Resolve an Official Account webhook to its tenant-owned channel."""
    if not isinstance(payload, dict):
        return None
    app_id = str(payload.get("app_id") or "").strip()
    recipient = payload.get("recipient")
    recipient_id = recipient.get("id") if isinstance(recipient, dict) else None
    oa_id = str(payload.get("oa_id") or recipient_id or "").strip()
    if not app_id and not oa_id:
        return None
    if tenant_db is not None:
        route_key = oa_id or app_id
        route = resolve_webhook_route(platform_db, "zalo", route_key)
        if route is None:
            return None
        channel = tenant_db.get(Channel, route.channel_id)
        if channel is None or channel.status != "active" or channel.channel_type != "zalo":
            return None
        return channel
    if settings.ENVIRONMENT.strip().lower() == "production":
        return None
    try:
        channels = platform_db.scalars(select(Channel).where(Channel.channel_type == "zalo", Channel.status == "active")).all()
    except OperationalError:
        platform_db.rollback()
        return None

    matches: list[Channel] = []
    for channel in channels:
        config = channel.config if isinstance(channel.config, dict) else {}
        provider = str(config.get("provider") or "").strip().lower()
        configured_app_id = str(
            config.get("oa_app_id") or config.get("app_id") or ""
        ).strip()
        configured_oa_id = str(
            config.get("oa_id") or channel.external_account_id or ""
        ).strip()
        if provider not in {"zalo_oa", "oa", "official_account"}:
            continue
        if configured_app_id and app_id and configured_app_id != app_id:
            continue
        if configured_oa_id and oa_id and configured_oa_id != oa_id:
            continue
        if configured_app_id or configured_oa_id:
            matches.append(channel)
    return matches[0] if len(matches) == 1 else None
