"""Fetch bounded inbound images from tenant-owned channel messages."""

from __future__ import annotations

from io import BytesIO
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx
from PIL import Image
from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations import get_channel_adapter
from app.models.channel import Channel
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.message_attachment import MessageAttachment
from app.services.channel_credentials import decrypt_token


MAX_IMAGE_BYTES = 8 * 1024 * 1024
_META_MEDIA_HOST_SUFFIXES = (".cdninstagram.com", ".fbcdn.net", ".fbsbx.com")


def _public_https_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host or parsed.username or parsed.password:
            return False
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            addresses = [
                ipaddress.ip_address(item[4][0].split("%", 1)[0])
                for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
            ]
        return bool(addresses) and all(address.is_global for address in addresses)
    except (OSError, ValueError):
        return False


def _image_url_for_message(db: Session, *, business_id: int, conversation_id: int, message_id: int) -> tuple[str | None, str]:
    source = db.query(Message).join(Conversation, Conversation.id == Message.conversation_id).filter(
        Message.id == message_id,
        Message.conversation_id == conversation_id,
        Message.direction == "inbound",
        Conversation.business_id == business_id,
    ).first()
    if source is None:
        return None, ""
    channel_type = str(source.channel or "").lower()
    if source.media_type == "image" and source.media_url:
        return str(source.media_url), channel_type
    attachment = db.query(MessageAttachment).filter(
        MessageAttachment.message_id == source.id,
        MessageAttachment.business_id == business_id,
        MessageAttachment.media_type == "image",
    ).order_by(MessageAttachment.id.asc()).first()
    if attachment is None:
        return None, channel_type
    if attachment.source_url:
        return str(attachment.source_url), channel_type
    if channel_type != "telegram" or not attachment.external_attachment_id:
        return None, channel_type
    channel = db.get(Channel, attachment.channel_id)
    if channel is None or channel.business_id != business_id or not channel.access_token_encrypted:
        return None, channel_type
    token = decrypt_token(channel.access_token_encrypted, settings.CHANNEL_ENCRYPTION_KEY)
    resolver = getattr(get_channel_adapter("telegram"), "resolve_attachment_url", None)
    if resolver is None:
        return None, channel_type
    return resolver(external_attachment_id=attachment.external_attachment_id, access_token=token), channel_type


def download_inbound_image_url(url: str, *, channel_type: str) -> tuple[bytes, str]:
    """Download one provider image without exposing URLs/tokens in errors."""
    headers = {"Accept": "image/jpeg,image/png,image/webp,*/*;q=0.2", "User-Agent": "SmartMerchantCRM/1.0"}
    if channel_type == "zalo":
        headers["User-Agent"] = "Mozilla/5.0 (CRM Chatbot media proxy)"
    elif channel_type in {"tiktok", "shopee"}:
        headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
            "Referer": "https://www.tiktok.com/" if channel_type == "tiktok" else "https://shopee.vn/",
        })

    current_url = url
    with httpx.Client(timeout=12, follow_redirects=False, trust_env=False) as client:
        for _ in range(4):
            if not _public_https_url(current_url):
                raise ValueError("Inbound image URL is not a public HTTPS address")
            parsed_host = (urlsplit(current_url).hostname or "").lower()
            if channel_type in {"facebook", "instagram"} and not any(
                parsed_host.endswith(suffix) for suffix in _META_MEDIA_HOST_SUFFIXES
            ):
                raise ValueError("Meta image URL is not hosted by an approved media CDN")
            with client.stream("GET", current_url, headers=headers) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("Inbound image redirect has no location")
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                telegram_binary_image = channel_type == "telegram" and content_type in {
                    "application/octet-stream",
                    "binary/octet-stream",
                }
                if content_type and not content_type.startswith("image/") and not telegram_binary_image:
                    raise ValueError("Provider attachment is not an image")
                image = bytearray()
                for chunk in response.iter_bytes():
                    image.extend(chunk)
                    if len(image) > MAX_IMAGE_BYTES:
                        raise ValueError("Inbound image exceeds the 8 MB analysis limit")
                with Image.open(BytesIO(image)) as opened:
                    if opened.format not in {"JPEG", "PNG", "WEBP"} or opened.width * opened.height > 20_000_000:
                        raise ValueError("Inbound image format or dimensions are not supported")
                    opened.load()
                    normalized = opened.convert("RGB")
                    result = BytesIO()
                    normalized.save(result, format="JPEG", quality=88, optimize=True)
                return result.getvalue(), "image/jpeg"
    raise ValueError("Inbound image has too many redirects")


def load_inbound_image(
    db: Session,
    *,
    business_id: int,
    conversation_id: int,
    message_id: int,
) -> tuple[bytes, str] | None:
    """Resolve and validate one latest customer photo; never fetch private hosts."""
    url, channel_type = _image_url_for_message(
        db, business_id=business_id, conversation_id=conversation_id, message_id=message_id,
    )
    return download_inbound_image_url(url, channel_type=channel_type) if url else None
