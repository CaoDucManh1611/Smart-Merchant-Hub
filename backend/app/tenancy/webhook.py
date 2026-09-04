"""Webhook authenticity and channel-account tenant resolution."""

import hashlib
import hmac

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.channel import Channel


def verify_meta_signature(raw_body: bytes, signature: str | None, app_secret: str) -> bool:
    if not signature or not signature.startswith("sha256=") or not app_secret:
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature[7:], expected)


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


def resolve_telegram_channel(db: Session, secret_token: str | None) -> Channel | None:
    """Resolve a Telegram webhook to its tenant-owned Channel.

    Telegram does not include the bot identity in an update. The secret
    header is therefore matched against the per-channel webhook secret; no
    global/default channel fallback is allowed.
    """
    if not secret_token:
        return None
    try:
        channels = db.scalars(
            select(Channel).where(
                Channel.channel_type == "telegram",
                Channel.status == "active",
            )
        ).all()
    except OperationalError:
        db.rollback()
        return None
    matches = [
        channel
        for channel in channels
        if isinstance(channel.config, dict)
        and hmac.compare_digest(str(channel.config.get("webhook_secret", "")), secret_token)
    ]
    return matches[0] if len(matches) == 1 else None


def resolve_zalo_channel(db: Session, secret_token: str | None) -> Channel | None:
    """Resolve a Zalo Bot webhook to its tenant-owned Channel.

    Zalo identifies the connection with the secret header, so the value is
    matched only against active ``zalo`` channels.  Ambiguous secrets are
    rejected instead of guessing a tenant.
    """
    if not secret_token:
        return None
    try:
        channels = db.scalars(
            select(Channel).where(
                Channel.channel_type == "zalo",
                Channel.status == "active",
            )
        ).all()
    except OperationalError:
        db.rollback()
        return None
    matches = [
        channel
        for channel in channels
        if isinstance(channel.config, dict)
        and hmac.compare_digest(str(channel.config.get("webhook_secret", "")), secret_token)
    ]
    return matches[0] if len(matches) == 1 else None
