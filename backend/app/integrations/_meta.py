"""Shared normalization helpers for Meta messaging webhook payloads."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.contracts.channel_event import (
    ChannelProvider,
    MediaType,
    MessageDirection,
    NormalizedAttachment,
    NormalizedChannelEvent,
    NormalizedMessage,
    unique_channel_events,
)


def parse_meta_events(
    payload: dict[str, Any],
    provider: ChannelProvider,
) -> list[NormalizedChannelEvent]:
    normalized: list[NormalizedChannelEvent] = []

    for entry in payload.get("entry") or []:
        account_id = str(entry.get("id") or "").strip()
        if not account_id:
            continue

        for messaging_event in entry.get("messaging") or []:
            message_payload = messaging_event.get("message") or {}
            message_id = str(message_payload.get("mid") or "").strip()
            if not message_id or message_payload.get("is_echo") is True:
                continue

            sender_id = str(
                (messaging_event.get("sender") or {}).get("id") or ""
            ).strip()
            recipient_id = str(
                (messaging_event.get("recipient") or {}).get("id") or ""
            ).strip()
            if not sender_id:
                continue

            attachments = _normalize_attachments(message_payload)
            text = message_payload.get("text")
            message_type = (
                MediaType.TEXT
                if isinstance(text, str) and text
                else attachments[0].media_type
                if attachments
                else MediaType.UNKNOWN
            )
            created_at = _from_milliseconds(messaging_event.get("timestamp"))

            message = NormalizedMessage(
                external_message_id=message_id,
                direction=MessageDirection.INBOUND,
                message_type=message_type,
                text=text if isinstance(text, str) else None,
                attachments=attachments,
                sender_external_id=sender_id,
                reply_to_external_message_id=(
                    message_payload.get("reply_to") or {}
                ).get("mid"),
                provider_created_at=created_at,
            )
            normalized.append(
                NormalizedChannelEvent(
                    provider=provider,
                    external_event_id=message_id,
                    event_type="message",
                    external_account_id=account_id,
                    sender_external_id=sender_id,
                    recipient_external_id=recipient_id or None,
                    provider_created_at=created_at,
                    raw_payload=messaging_event,
                    messages=[message],
                )
            )

    return unique_channel_events(normalized)


def _normalize_attachments(
    message_payload: dict[str, Any],
) -> list[NormalizedAttachment]:
    result: list[NormalizedAttachment] = []

    for raw_attachment in message_payload.get("attachments") or []:
        raw_type = str(raw_attachment.get("type") or "unknown").lower()
        media_type = _media_type(raw_type)
        attachment_payload = raw_attachment.get("payload") or {}
        url = (
            attachment_payload.get("url")
            or (raw_attachment.get("image_data") or {}).get("url")
            or raw_attachment.get("video_url")
            or raw_attachment.get("file_url")
        )
        metadata = {
            "provider_type": raw_type,
            "mime_type": raw_attachment.get("mime_type") or attachment_payload.get("mime_type"),
            "file_name": raw_attachment.get("file_name") or attachment_payload.get("file_name"),
            "duration_ms": raw_attachment.get("duration_ms") or attachment_payload.get("duration_ms"),
        }
        metadata = {key: value for key, value in metadata.items() if value is not None}
        result.append(
            NormalizedAttachment(
                media_type=media_type,
                url=url,
                external_attachment_id=(
                    str(raw_attachment.get("id") or attachment_payload.get("id"))
                    if (raw_attachment.get("id") or attachment_payload.get("id"))
                    else None
                ),
                metadata=metadata,
            )
        )

    return result


def _media_type(raw_type: str) -> MediaType:
    aliases = {
        "photo": MediaType.IMAGE,
        "reel": MediaType.VIDEO,
    }
    if raw_type in aliases:
        return aliases[raw_type]
    try:
        return MediaType(raw_type)
    except ValueError:
        return MediaType.UNKNOWN


def _from_milliseconds(value: Any) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)
