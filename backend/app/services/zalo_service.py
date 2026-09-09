"""Tenant-scoped Zalo Bot outbound operations."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.zalo import ZaloAdapter
from app.models.channel import Channel
from app.models.conversation import Conversation
from app.services.channel_credentials import decrypt_token
from app.services.channel_retry import run_with_provider_retry


def send_zalo_message(
    *,
    db: Session,
    business_id: int,
    conversation_id: int,
    recipient_id: str,
    text: str,
) -> dict:
    """Send through the active Zalo channel attached to a conversation."""
    channel_id = db.scalar(
        select(Conversation.channel_id).where(
            Conversation.id == conversation_id,
            Conversation.business_id == business_id,
            Conversation.channel == "zalo",
        )
    )
    if channel_id is None:
        raise LookupError("Zalo conversation is not linked to a channel")

    channel = db.scalar(
        select(Channel).where(
            Channel.id == channel_id,
            Channel.business_id == business_id,
            Channel.channel_type == "zalo",
            Channel.status == "active",
        )
    )
    if channel is None or not channel.access_token_encrypted:
        raise LookupError("Active Zalo channel credentials not found")

    access_token = decrypt_token(
        channel.access_token_encrypted,
        settings.CHANNEL_ENCRYPTION_KEY,
    )
    config = channel.config if isinstance(channel.config, dict) else {}
    provider = config.get("provider", "bot")
    send_kwargs = {
        "recipient_external_id": recipient_id,
        "text": text,
        "access_token": access_token,
    }
    if str(provider).strip().lower() in {"oa", "zalo_oa", "official_account"}:
        send_kwargs["provider"] = str(provider)
    result = run_with_provider_retry(
        provider="zalo",
        operation="text_send",
        request=lambda: ZaloAdapter().send_message(**send_kwargs),
    )
    if result.get("ok") is False:
        raise RuntimeError(result.get("description") or "Zalo rejected the message")

    raw_message_id = result.get("message_id") or (result.get("result") or {}).get("message_id")
    if raw_message_id is not None:
        result = dict(result)
        result["message_id"] = f"zalo:{channel.external_account_id}:{raw_message_id}"
    return result


def send_zalo_media(
    *,
    db: Session,
    business_id: int,
    conversation_id: int,
    recipient_id: str,
    media_type: str,
    media_url: str,
    caption: str | None = None,
) -> dict:
    """Send Bot Creator media using the tenant-owned bot token."""
    channel_id = db.scalar(
        select(Conversation.channel_id).where(
            Conversation.id == conversation_id,
            Conversation.business_id == business_id,
            Conversation.channel == "zalo",
        )
    )
    if channel_id is None:
        raise LookupError("Zalo conversation is not linked to a channel")
    channel = db.scalar(
        select(Channel).where(
            Channel.id == channel_id,
            Channel.business_id == business_id,
            Channel.channel_type == "zalo",
            Channel.status == "active",
        )
    )
    if channel is None or not channel.access_token_encrypted:
        raise LookupError("Active Zalo channel credentials not found")
    access_token = decrypt_token(channel.access_token_encrypted, settings.CHANNEL_ENCRYPTION_KEY)
    config = channel.config if isinstance(channel.config, dict) else {}
    provider = str(config.get("provider", "bot"))
    media_kwargs = {
        "recipient_external_id": recipient_id,
        "media_type": media_type,
        "media_url": media_url,
        "caption": caption,
        "access_token": access_token,
    }
    if provider.strip().lower() in {"oa", "zalo_oa", "official_account"}:
        media_kwargs["provider"] = provider
    result = run_with_provider_retry(
        provider="zalo",
        operation=f"{media_type}_send",
        request=lambda: ZaloAdapter().send_media(**media_kwargs),
    )
    if result.get("ok") is False:
        raise RuntimeError(result.get("description") or "Zalo rejected the media")
    raw_message_id = result.get("message_id") or (result.get("result") or {}).get("message_id")
    if raw_message_id is not None:
        result = dict(result)
        result["message_id"] = f"zalo:{channel.external_account_id}:{raw_message_id}"
    return result
