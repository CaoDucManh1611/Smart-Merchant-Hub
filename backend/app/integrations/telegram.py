"""Telegram Bot API adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from app.contracts.channel_event import (
    ChannelProvider,
    MediaType,
    MessageDirection,
    NormalizedAttachment,
    NormalizedChannelEvent,
    NormalizedMessage,
)


class TelegramAdapter:
    def verify_webhook(self, payload: bytes, headers: dict[str, str]) -> bool:
        # Telegram authenticates webhooks with the secret token header. The
        # expected value is channel-owned and checked by the webhook route.
        return bool(headers.get("x-telegram-bot-api-secret-token"))

    def parse_events(
        self,
        payload: dict[str, Any],
        *,
        external_account_id: str,
    ) -> list[NormalizedChannelEvent]:
        update_id = payload.get("update_id")
        message = payload.get("message") or payload.get("edited_message") or {}
        sender = message.get("from") or {}
        chat = message.get("chat") or {}
        message_id = message.get("message_id")
        sender_id = sender.get("id") or chat.get("id")
        if update_id is None or message_id is None or sender_id is None:
            return []
        if not str(external_account_id).strip():
            raise ValueError("Telegram external_account_id is required")

        attachments: list[NormalizedAttachment] = []
        message_type = MediaType.TEXT
        text = message.get("text") or message.get("caption")

        def add_attachment(media_type: MediaType, payload_value: Any, **metadata: Any) -> None:
            if not isinstance(payload_value, dict) or not payload_value.get("file_id"):
                return
            clean_metadata = {
                key: value
                for key, value in metadata.items()
                if value is not None
            }
            clean_metadata.update({
                key: value
                for key, value in payload_value.items()
                if key in {"file_unique_id", "mime_type", "file_size", "width", "height", "emoji", "is_animated", "is_video"}
                and value is not None
            })
            attachments.append(NormalizedAttachment(
                media_type=media_type,
                external_attachment_id=str(payload_value["file_id"]),
                metadata=clean_metadata,
            ))

        # A Telegram update normally carries one media object, but keeping
        # every present variant makes the canonical contract safe for bridge
        # integrations and synthetic multi-media updates.
        photo = message.get("photo")
        if isinstance(photo, list) and photo:
            add_attachment(MediaType.IMAGE, photo[-1])
        add_attachment(MediaType.AUDIO, message.get("audio"))
        add_attachment(MediaType.AUDIO, message.get("voice"), voice=True)
        add_attachment(MediaType.STICKER, message.get("sticker"))
        add_attachment(MediaType.VIDEO, message.get("video"))
        add_attachment(MediaType.FILE, message.get("document"), file_name=(message.get("document") or {}).get("file_name"))
        if attachments:
            message_type = attachments[0].media_type
        elif not isinstance(text, str) or not text:
            message_type = MediaType.UNKNOWN

        occurred_at = None
        if isinstance(message.get("date"), (int, float)):
            occurred_at = datetime.fromtimestamp(message["date"], tz=UTC)
        external_event_id = f"telegram:{update_id}:{message_id}"
        normalized_message = NormalizedMessage(
            external_message_id=external_event_id,
            direction=MessageDirection.INBOUND,
            message_type=message_type,
            text=text if isinstance(text, str) else None,
            attachments=attachments,
            sender_external_id=str(sender_id),
            provider_created_at=occurred_at,
            metadata={"chat_id": str(chat.get("id", sender_id))},
        )
        return [NormalizedChannelEvent(
            provider=ChannelProvider.TELEGRAM,
            external_event_id=external_event_id,
            event_type="message",
            external_account_id=str(external_account_id),
            sender_external_id=str(sender_id),
            recipient_external_id=str(chat.get("id")) if chat.get("id") is not None else None,
            provider_created_at=occurred_at,
            raw_payload=payload,
            messages=[normalized_message],
        )]

    def send_message(self, *, recipient_external_id: str, text: str, access_token: str) -> dict[str, Any]:
        response = httpx.post(
            f"https://api.telegram.org/bot{access_token}/sendMessage",
            json={"chat_id": recipient_external_id, "text": text},
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    def send_media(
        self,
        *,
        recipient_external_id: str,
        media_type: str,
        media_url: str,
        access_token: str,
        caption: str | None = None,
    ) -> dict[str, Any]:
        methods = {
            "image": ("sendPhoto", "photo"),
            "audio": ("sendAudio", "audio"),
            "sticker": ("sendSticker", "sticker"),
            "video": ("sendVideo", "video"),
            "file": ("sendDocument", "document"),
        }
        try:
            method, field = methods[str(media_type).strip().lower()]
        except KeyError as exc:
            raise ValueError(f"Telegram không hỗ trợ media_type: {media_type}") from exc
        media_url = str(media_url or "").strip()
        if not media_url:
            raise ValueError("Telegram media_url là bắt buộc")
        payload: dict[str, Any] = {"chat_id": recipient_external_id, field: media_url}
        if caption and field != "sticker":
            payload["caption"] = str(caption)[:1024]
        response = httpx.post(
            f"https://api.telegram.org/bot{access_token}/{method}",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def download_attachment(self, *, attachment_url: str, access_token: str) -> bytes:
        response = httpx.get(attachment_url, headers={"Authorization": f"Bearer {access_token}"}, timeout=30)
        response.raise_for_status()
        return response.content

    def resolve_attachment_url(self, *, external_attachment_id: str, access_token: str) -> str | None:
        """Resolve a Telegram file_id without exposing the bot token to clients."""
        response = httpx.get(
            f"https://api.telegram.org/bot{access_token}/getFile",
            params={"file_id": external_attachment_id},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        file_path = (payload.get("result") or {}).get("file_path")
        if not file_path:
            return None
        return f"https://api.telegram.org/file/bot{access_token}/{file_path}"
