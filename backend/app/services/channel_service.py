"""Tenant-scoped channel connection access."""

from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.channel import Channel
from app.services.channel_credentials import decrypt_token
from app.services.channel_credentials import encrypt_token
from app.services.quota_service import reserve_quota


TOKEN_EXPIRY_WARNING = timedelta(days=7)


def channel_credential_status(
    channel: Channel | None,
    *,
    now: datetime | None = None,
) -> dict[str, str | bool | None]:
    """Expose a non-secret credential-health summary for a channel."""
    if channel is None or not channel.access_token_encrypted:
        return {"state": "missing", "expires_at": None, "reauthorization_required": True}

    config = channel.config if isinstance(channel.config, dict) else {}
    expires_raw = config.get("token_expires_at")
    if not expires_raw:
        # Some provider-issued tokens do not publish an expiry.  Do not mark
        # them healthy forever; callers can show that the expiry is unknown.
        return {"state": "unknown", "expires_at": None, "reauthorization_required": False}
    try:
        expires_at = datetime.fromisoformat(str(expires_raw).replace("Z", "+00:00"))
    except ValueError:
        return {"state": "invalid_expiry", "expires_at": None, "reauthorization_required": True}
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    current = now or datetime.now(UTC)
    if expires_at <= current:
        state = "expired"
    elif expires_at <= current + TOKEN_EXPIRY_WARNING:
        state = "expiring"
    else:
        state = "valid"
    return {
        "state": state,
        "expires_at": expires_at.isoformat(),
        "reauthorization_required": state in {"expired", "invalid_expiry"},
    }


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
    needs_slot = channel is None or channel.status != "active"
    if needs_slot:
        reserve_quota(
            db,
            business_id,
            "connected_channels",
            idempotency_key=f"channel:{channel_type}:{external_account_id}",
        )
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
