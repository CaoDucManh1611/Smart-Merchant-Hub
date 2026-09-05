"""Tenant-scoped channel connection access."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.channel import Channel
from app.services.channel_credentials import decrypt_token
from app.services.channel_credentials import encrypt_token


def get_active_channel(
    db: Session,
    business_id: int,
    channel_type: str,
    external_account_id: str,
) -> Channel | None:
    return db.scalar(
        select(Channel).where(
            Channel.business_id == business_id,
            Channel.channel_type == channel_type,
            Channel.external_account_id == external_account_id,
            Channel.status == "active",
        )
    )


def get_single_active_channel(db: Session, business_id: int, channel_type: str) -> Channel:
    channels = db.scalars(select(Channel).where(
        Channel.business_id == business_id,
        Channel.channel_type == channel_type,
        Channel.status == "active",
    )).all()
    if len(channels) != 1:
        raise LookupError("Expected exactly one active tenant channel")
    return channels[0]


def get_active_channel_token(
    db: Session,
    business_id: int,
    channel_type: str,
    external_account_id: str,
) -> str:
    channel = get_active_channel(db, business_id, channel_type, external_account_id)
    if channel is None or not channel.access_token_encrypted:
        raise LookupError("Active tenant channel credentials not found")
    return decrypt_token(channel.access_token_encrypted, settings.CHANNEL_ENCRYPTION_KEY)


def upsert_channel_connection(
    db: Session,
    *,
    business_id: int,
    channel_type: str,
    external_account_id: str,
    name: str,
    access_token: str,
    config: dict | None = None,
    encryption_key: str | None = None,
) -> Channel:
    """Create/update one globally-owned external account for one tenant."""
    channel = db.scalar(
        select(Channel).where(
            Channel.channel_type == channel_type,
            Channel.external_account_id == external_account_id,
        )
    )
    if channel is not None and channel.business_id != business_id:
        raise PermissionError("External channel account already belongs to another business")
    if channel is None:
        channel = Channel(
            business_id=business_id,
            channel_type=channel_type,
            external_account_id=external_account_id,
            name=name,
        )
        db.add(channel)
    channel.name = name
    channel.access_token_encrypted = encrypt_token(
        access_token, encryption_key or settings.CHANNEL_ENCRYPTION_KEY
    )
    channel.access_token = None
    channel.status = "active"
    channel.config = config
    channel.connected_at = datetime.now(timezone.utc).replace(tzinfo=None)
    channel.disconnected_at = None
    db.commit()
    db.refresh(channel)
    return channel
