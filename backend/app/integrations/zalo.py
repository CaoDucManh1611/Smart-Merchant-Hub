"""Zalo Bot Creator adapter for inbound and outbound messages."""

from __future__ import annotations

from datetime import UTC, datetime
import json
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


ZALO_BOT_API_BASE = "https://bot-api.zaloplatforms.com/bot"
ZALO_OA_MESSAGE_API = "https://openapi.zalo.me/v3.0/oa/message/cs"
ZALO_OA_PROFILE_API = "https://openapi.zalo.me/v3.0/oa/user/detail"


def _created_at(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    # Zalo examples use milliseconds, while some SDKs expose seconds.
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    try:
        return datetime.fromtimestamp(timestamp, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _attachment_value(value: Any) -> tuple[str | None, str | None]:
    """Return (public URL, provider attachment id) from common Zalo shapes."""
    if isinstance(value, dict):
        # Bot Creator currently sends media as a direct ``photo_url`` (or
        # ``voice_url``), while bridge/OA payloads commonly wrap it in
        # ``url``, ``payload.url`` or ``data.url``.  Accept all of these
        # without exposing provider tokens to the browser.
        nested = value.get("payload") or value.get("data") or value.get("attachment")
        url = (
            value.get("url")
            or value.get("download_url")
            or value.get("file_url")
            or value.get("photo_url")
            or value.get("voice_url")
            or value.get("audio_url")
            or value.get("sticker_url")
        )
        identifier = (
            value.get("file_id")
            or value.get("attachment_id")
            or value.get("id")
            or value.get("sticker")
        )
        if not url and isinstance(nested, (dict, list)):
            nested_url, nested_identifier = _attachment_value(nested)
            url = nested_url
            identifier = identifier or nested_identifier
        return (
            str(url) if url else None,
            str(identifier) if identifier else None,
        )
    if isinstance(value, list):
        return _attachment_value(value[-1]) if value else (None, None)
    if value is None:
        return None, None
    value = str(value)
    if value.startswith(("http://", "https://")):
        return value, None
    return None, value


def _avatar_url(sender: dict[str, Any]) -> str | None:
    """Extract only a public HTTP(S) avatar URL from common Zalo payloads."""
    for key in ("avatar_url", "avatar", "photo_url", "profile_photo", "profile_pic"):
        value = sender.get(key)
        url, _identifier = _attachment_value(value)
        if url and url.startswith(("http://", "https://")):
            return url
    return None


class ZaloAdapter:
    """Translate Zalo Bot webhook payloads into the shared CRM contract."""

    def verify_webhook(self, payload: bytes, headers: dict[str, str]) -> bool:
        return bool(headers.get("x-bot-api-secret-token"))

    def fetch_user_profile(
        self,
        *,
        user_id: str,
        access_token: str,
    ) -> dict[str, str | None]:
        """Fetch optional profile fields through the Zalo OA user API.

        Bot Creator webhooks do not consistently include an avatar.  An OA
        access token can enrich the profile without changing the webhook
        contract.  Callers deliberately treat provider errors as optional
        enrichment failures so receiving a message never fails.
        """
        user_id = str(user_id or "").strip()
        access_token = str(access_token or "").strip()
        if not user_id or not access_token:
            raise ValueError("Zalo user_id and access_token are required")
        response = httpx.get(
            ZALO_OA_PROFILE_API,
            params={"data": json.dumps({"user_id": user_id}, separators=(",", ":"))},
            headers={"access_token": access_token},
            timeout=15,
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("error") not in (None, 0):
            raise ValueError("Zalo profile lookup failed")
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        avatar = _avatar_url(data)
        return {
            "display_name": str(data.get("display_name") or data.get("name") or "").strip() or None,
            "avatar_url": avatar,
        }

    def parse_events(
        self,
        payload: dict[str, Any],
        *,
        external_account_id: str,
        raw_payload: dict[str, Any] | None = None,
    ) -> list[NormalizedChannelEvent]:
        external_account_id = str(external_account_id or "").strip()
        if not external_account_id:
            raise ValueError("Zalo external_account_id is required")
        if not isinstance(payload, dict):
            return []

        # Official Account webhooks use sender/recipient/event_name at the
        # top level, while Bot Creator puts the sender inside message.from.
        # Convert the OA envelope into the shared parser shape so both
        # integrations keep identical persistence and Customer 360 behavior.
        event_name = str(payload.get("event_name") or "").strip().lower()
        if event_name.startswith("user_") and isinstance(payload.get("sender"), dict):
            sender = payload["sender"]
            message = payload.get("message")
            if not isinstance(message, dict):
                return []
            sender_id = sender.get("id")
            message_id = message.get("msg_id") or message.get("message_id") or payload.get("msg_id")
            if sender_id is None or message_id is None:
                return []
            normalized_message = dict(message)
            normalized_message.update(
                {
                    "message_id": message_id,
                    "date": payload.get("timestamp"),
                    "from_id": sender_id,
                    "from_display_name": sender.get("display_name"),
                    "from_avatar": sender.get("avatar_url") or sender.get("avatar"),
                    "chat_id": sender_id,
                    "chat_type": "PRIVATE",
                }
            )
            normalized_payload = {
                "event_name": payload.get("event_name"),
                "message": normalized_message,
            }
            return self.parse_events(
                normalized_payload,
                external_account_id=external_account_id,
                raw_payload=payload,
            )

        message = payload.get("message")
        if not isinstance(message, dict):
            return []

        sender = message.get("from") if isinstance(message.get("from"), dict) else {}
        if not sender and message.get("from_id") is not None:
            sender = {
                "id": message.get("from_id"),
                "display_name": message.get("from_display_name"),
                "avatar_url": message.get("from_avatar") or message.get("from_avatar_url"),
            }
        elif sender:
            # Conversation-history bridges expose profile fields alongside
            # ``from_id`` instead of nesting them in ``from``.  Preserve the
            # nested sender shape while accepting those flat aliases too.
            sender = dict(sender)
            sender.setdefault(
                "avatar_url",
                message.get("from_avatar") or message.get("from_avatar_url"),
            )
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        if not chat:
            chat = {
                "id": message.get("chat_id") or message.get("conversation_id") or message.get("to_id"),
                "chat_type": message.get("chat_type"),
            }
        if sender.get("is_bot") is True:
            return []

        message_id = (
            message.get("message_id")
            or payload.get("update_id")
            or payload.get("event_id")
            or payload.get("msg_id")
        )
        sender_id = sender.get("id") or chat.get("id")
        chat_id = chat.get("id") or sender_id
        if message_id is None or sender_id is None or chat_id is None:
            return []

        event_name = str(payload.get("event_name") or "message")
        text = message.get("text")
        if not isinstance(text, str):
            text = message.get("caption") if isinstance(message.get("caption"), str) else None
        if not isinstance(text, str):
            text = message.get("message") if isinstance(message.get("message"), str) else None

        attachments: list[NormalizedAttachment] = []

        def add_attachment(media_type: MediaType, value: Any, **metadata: Any) -> None:
            if value is None:
                return
            url, identifier = _attachment_value(value)
            clean_metadata = {key: val for key, val in metadata.items() if val is not None}
            if isinstance(value, dict):
                for key in ("mime_type", "file_name", "filename", "duration", "duration_ms", "width", "height"):
                    if value.get(key) is not None:
                        clean_metadata[key] = value[key]
            # A payload can expose the same media in both a typed field and
            # ``attachments``. Keep one canonical row so retries do not render
            # duplicate bubbles in the inbox.
            if any(
                item.media_type == media_type
                and item.url == url
                and item.external_attachment_id == identifier
                for item in attachments
            ):
                return
            attachments.append(NormalizedAttachment(
                media_type=media_type,
                url=url,
                external_attachment_id=identifier,
                metadata=clean_metadata,
            ))

        photo = message.get("photo_url") or message.get("image_url") or message.get("photo") or message.get("image")
        audio = message.get("audio_url") or message.get("voice_url") or message.get("audio") or message.get("voice")
        sticker = message.get("sticker_url") or message.get("sticker")
        video = message.get("video_url") or message.get("video")
        file_value = message.get("file_url") or message.get("document") or message.get("file")
        event_name_lower = event_name.lower()
        flat_type = str(message.get("type") or message.get("message_type") or "").strip().lower()
        if flat_type in {"photo", "image", "gif", "picture"} and photo is None:
            photo = message.get("url") or message.get("thumb")
        if flat_type in {"voice", "audio", "sound"} and audio is None:
            audio = message.get("url")
        if flat_type in {"sticker", "sticker_image"} and sticker is None:
            sticker = message.get("url") or message.get("thumb")
        if flat_type in {"video", "clip"} and video is None:
            video = message.get("url")
        if flat_type in {"file", "document", "attachment"} and file_value is None:
            file_value = message.get("url")

        if "image" in event_name_lower or "photo" in event_name_lower or photo is not None:
            add_attachment(
                MediaType.IMAGE,
                photo,
                thumb_url=message.get("thumb"),
            )
        if "audio" in event_name_lower or "voice" in event_name_lower or audio is not None:
            add_attachment(MediaType.AUDIO, audio)
        if "sticker" in event_name_lower or sticker is not None:
            add_attachment(MediaType.STICKER, sticker)
        if "video" in event_name_lower or video is not None:
            add_attachment(MediaType.VIDEO, video)
        if "file" in event_name_lower or "document" in event_name_lower or file_value is not None:
            add_attachment(MediaType.FILE, file_value)

        # Some Zalo bridges use the same attachment envelope as Meta:
        # ``attachments: [{type, payload: {url}}]``. Parse every item rather
        # than silently dropping it when no provider-specific field exists.
        raw_attachments = message.get("attachments") or message.get("attachment") or []
        if isinstance(raw_attachments, dict):
            raw_attachments = [raw_attachments]
        if isinstance(raw_attachments, list):
            for raw_attachment in raw_attachments:
                if not isinstance(raw_attachment, dict):
                    continue
                raw_kind = str(
                    raw_attachment.get("media_type")
                    or raw_attachment.get("type")
                    or "file"
                ).strip().lower()
                if raw_kind in {"photo", "image", "gif", "picture"}:
                    kind = MediaType.IMAGE
                elif raw_kind in {"voice", "audio", "sound"}:
                    kind = MediaType.AUDIO
                elif raw_kind in {"sticker", "sticker_image"}:
                    kind = MediaType.STICKER
                elif raw_kind in {"video", "clip"}:
                    kind = MediaType.VIDEO
                else:
                    kind = MediaType.FILE
                add_attachment(
                    kind,
                    raw_attachment,
                    thumb_url=raw_attachment.get("thumb") or raw_attachment.get("thumbnail"),
                )
        if attachments:
            message_type = attachments[0].media_type
        elif isinstance(text, str) and text:
            message_type = MediaType.TEXT
        else:
            message_type = MediaType.UNKNOWN

        external_event_id = f"zalo:{external_account_id}:{message_id}"
        occurred_at = _created_at(message.get("date"))
        normalized_message = NormalizedMessage(
            external_message_id=external_event_id,
            direction=MessageDirection.INBOUND,
            message_type=message_type,
            text=text,
            attachments=attachments,
            sender_external_id=str(sender_id),
            provider_created_at=occurred_at,
            metadata={
                "chat_id": str(chat_id),
                "chat_type": str(chat.get("chat_type") or "PRIVATE"),
                "event_name": event_name,
                "display_name": sender.get("display_name"),
                "avatar_url": _avatar_url(sender),
            },
        )
        return [
            NormalizedChannelEvent(
                provider=ChannelProvider.ZALO,
                external_event_id=external_event_id,
                event_type=event_name,
                external_account_id=external_account_id,
                sender_external_id=str(sender_id),
                recipient_external_id=str(chat_id),
                provider_created_at=occurred_at,
                raw_payload=raw_payload if raw_payload is not None else payload,
                messages=[normalized_message],
            )
        ]

    def send_message(
        self,
        *,
        recipient_external_id: str,
        text: str,
        access_token: str,
        provider: str = "bot",
    ) -> dict[str, Any]:
        recipient_external_id = str(recipient_external_id or "").strip()
        text = str(text or "").strip()
        access_token = str(access_token or "").strip()
        if not recipient_external_id:
            raise ValueError("Zalo recipient_external_id is required")
        if not text:
            raise ValueError("Zalo message text is required")
        if not access_token:
            raise ValueError("Zalo access token is required")
        if str(provider).strip().lower() in {"oa", "zalo_oa", "official_account"}:
            response = httpx.post(
                ZALO_OA_MESSAGE_API,
                headers={"access_token": access_token},
                json={
                    "recipient": {"user_id": recipient_external_id},
                    "message": {"text": text[:2000]},
                },
                timeout=15,
            )
            response.raise_for_status()
            return response.json()
        response = httpx.post(
            f"{ZALO_BOT_API_BASE}{access_token}/sendMessage",
            json={"chat_id": recipient_external_id, "text": text[:2000]},
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
        provider: str = "bot",
    ) -> dict[str, Any]:
        media_type = str(media_type or "").strip().lower()
        media_url = str(media_url or "").strip()
        if not media_url:
            raise ValueError("Zalo media_url là bắt buộc")
        if str(provider).strip().lower() in {"oa", "zalo_oa", "official_account"}:
            if media_type not in {"image", "gif"}:
                raise ValueError("Zalo OA hiện hỗ trợ gửi image/gif qua CRM")
            message: dict[str, Any] = {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "media",
                        "elements": [
                            {
                                "media_type": "image" if media_type == "image" else "gif",
                                "url": media_url,
                            }
                        ],
                    },
                }
            }
            if caption:
                message["text"] = str(caption)[:2000]
            response = httpx.post(
                ZALO_OA_MESSAGE_API,
                headers={"access_token": access_token},
                json={
                    "recipient": {"user_id": recipient_external_id},
                    "message": message,
                },
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        methods: dict[str, tuple[str, str]] = {
            "image": ("sendPhoto", "photo"),
            "audio": ("sendVoice", "voice_url"),
            "sticker": ("sendSticker", "sticker"),
        }
        if media_type not in methods:
            raise ValueError("Zalo Bot hiện chỉ hỗ trợ gửi image, audio/voice và sticker")
        method, field = methods[media_type]
        payload: dict[str, Any] = {"chat_id": recipient_external_id, field: media_url}
        if caption and media_type == "image":
            payload["caption"] = str(caption)[:2000]
        response = httpx.post(
            f"{ZALO_BOT_API_BASE}{access_token}/{method}",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def download_attachment(self, *, attachment_url: str, access_token: str) -> bytes:
        response = httpx.get(attachment_url, timeout=30)
        response.raise_for_status()
        return response.content
