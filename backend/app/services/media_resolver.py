"""Tenant-safe retrieval of provider-backed message attachments."""

from __future__ import annotations

import hashlib
import hmac
import time

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations import get_channel_adapter
from app.models.channel import Channel
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.message_attachment import MessageAttachment
from app.services.channel_credentials import decrypt_token
from app.tenancy.context import TenantContext


MEDIA_URL_TTL_SECONDS = 15 * 60


def _media_signing_secret() -> bytes:
    """Return a stable signing key for browser-loadable media URLs."""
    configured = str(settings.CHANNEL_ENCRYPTION_KEY or "").strip()
    # Development environments may not have the encryption key configured.
    # Keep the URL mechanism usable there while deployments with encrypted
    # channel credentials automatically get a deployment-specific key.
    return (configured or f"{settings.APP_NAME}:media-url").encode("utf-8")


def _media_signature(*, attachment_id: int, business_id: int, expires: int) -> str:
    payload = f"{int(attachment_id)}:{int(business_id)}:{int(expires)}".encode("utf-8")
    return hmac.new(_media_signing_secret(), payload, hashlib.sha256).hexdigest()


def build_media_url(
    *,
    attachment_id: int,
    business_id: int,
    ttl_seconds: int = MEDIA_URL_TTL_SECONDS,
) -> str:
    """Build a tenant-bound URL that works from an ``img``/``audio`` tag.

    Those browser elements cannot attach the SPA's ``X-Business-Id`` header,
    so the API accepts this signed, expiring alternative.  The signature binds
    both the attachment and tenant and is checked before any bytes are read.
    """
    expires = int(time.time()) + max(1, int(ttl_seconds))
    signature = _media_signature(
        attachment_id=attachment_id,
        business_id=business_id,
        expires=expires,
    )
    return (
        f"/api/media/{int(attachment_id)}"
        f"?business_id={int(business_id)}&expires={expires}&signature={signature}"
    )


def verify_media_url(
    *,
    attachment_id: int,
    business_id: int,
    expires: int,
    signature: str,
) -> bool:
    if int(expires) < int(time.time()):
        return False
    expected = _media_signature(
        attachment_id=attachment_id,
        business_id=business_id,
        expires=expires,
    )
    return hmac.compare_digest(str(signature or ""), expected)


def _provider_url(
    db: Session,
    *,
    attachment: MessageAttachment,
    channel: Channel,
) -> str | None:
    if attachment.source_url:
        return attachment.source_url
    if not attachment.external_attachment_id:
        return None
    if channel.channel_type != "telegram":
        return None
    if not channel.access_token_encrypted:
        return None
    token = decrypt_token(channel.access_token_encrypted, settings.CHANNEL_ENCRYPTION_KEY)
    adapter = get_channel_adapter(channel.channel_type)
    resolver = getattr(adapter, "resolve_attachment_url", None)
    if resolver is None:
        return None
    return resolver(
        external_attachment_id=attachment.external_attachment_id,
        access_token=token,
    )


def resolve_media_response(
    db: Session,
    *,
    attachment_id: int,
    tenant: TenantContext,
) -> StreamingResponse:
    row = db.execute(
        select(MessageAttachment, Message, Conversation, Channel)
        .join(Message, Message.id == MessageAttachment.message_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(Channel, Channel.id == MessageAttachment.channel_id)
        .where(
            MessageAttachment.id == attachment_id,
            MessageAttachment.business_id == tenant.business_id,
            Conversation.business_id == tenant.business_id,
            Channel.business_id == tenant.business_id,
            Conversation.channel_id == MessageAttachment.channel_id,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Media attachment not found")

    attachment, _message, _conversation, channel = row
    try:
        url = _provider_url(db, attachment=attachment, channel=channel)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to resolve provider media") from exc
    if not url:
        raise HTTPException(status_code=404, detail="Media URL is not available")

    try:
        # Zalo's short-lived media URLs are served by an edge that may reject
        # the default ``python-httpx`` user agent.  Use a normal browser-like
        # accept list for provider media while keeping the token out of the
        # URL and response sent to the SPA.
        request_headers = None
        if channel.channel_type == "zalo":
            request_headers = {
                "User-Agent": "Mozilla/5.0 (CRM Chatbot media proxy)",
                "Accept": "image/avif,image/webp,image/apng,image/*,audio/*,video/*,*/*;q=0.8",
            }
        response = httpx.get(
            url,
            headers=request_headers,
            timeout=30,
            follow_redirects=True,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Unable to download provider media") from exc

    media_type = (
        attachment.mime_type
        or response.headers.get("content-type")
        or "application/octet-stream"
    )
    headers = {"Cache-Control": "private, max-age=300"}
    if attachment.file_name:
        headers["Content-Disposition"] = f'inline; filename="{attachment.file_name}"'
    return StreamingResponse(iter([response.content]), media_type=media_type, headers=headers)
