"""Persistence helpers for the canonical omnichannel media contract."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.channel_event import NormalizedAttachment
from app.models.message_attachment import MessageAttachment
from app.models.message import Message
from app.models.channel import Channel
from app.models.conversation import Conversation


def _as_attachment(value: NormalizedAttachment | dict[str, Any]) -> NormalizedAttachment:
    if isinstance(value, NormalizedAttachment):
        return value
    return NormalizedAttachment.model_validate(value)


def _duration_ms(metadata: dict[str, Any]) -> int | None:
    value = metadata.get("duration_ms")
    if value is None:
        value = metadata.get("duration")
        if value is not None:
            try:
                return int(float(value) * 1000)
            except (TypeError, ValueError):
                return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def save_message_attachments(
    db: Session,
    *,
    message_id: int,
    business_id: int,
    channel_id: int,
    attachments: Iterable[NormalizedAttachment | dict[str, Any]],
) -> list[MessageAttachment]:
    """Persist all attachments for a message and return them in input order.

    Provider deliveries can be retried after the message row already exists.
    The provider identity index is used where available and the message-local
    fallback prevents duplicate rows for URL-only attachments.
    """

    parent = db.scalar(
        select(Message, Conversation, Channel)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(Channel, Channel.id == channel_id)
        .where(
            Message.id == message_id,
            Conversation.business_id == business_id,
            Conversation.channel_id == channel_id,
            Channel.business_id == business_id,
        )
    )
    if parent is None:
        raise ValueError("Message, conversation, channel and tenant do not match")

    persisted: list[MessageAttachment] = []
    for raw in attachments:
        item = _as_attachment(raw)
        metadata = dict(item.metadata or {})
        external_id = item.external_attachment_id
        existing = None
        if external_id:
            existing = db.scalar(
                select(MessageAttachment).where(
                    MessageAttachment.channel_id == channel_id,
                    MessageAttachment.message_id == message_id,
                    MessageAttachment.external_attachment_id == external_id,
                )
            )
        else:
            existing = db.scalar(
                select(MessageAttachment).where(
                    MessageAttachment.message_id == message_id,
                    MessageAttachment.media_type == item.media_type.value,
                    MessageAttachment.source_url == item.url,
                )
            )
        if existing is not None:
            if existing.business_id != business_id or existing.message_id != message_id:
                raise ValueError("Attachment provider identity belongs to another tenant or message")
            persisted.append(existing)
            continue

        row = MessageAttachment(
            business_id=business_id,
            message_id=message_id,
            channel_id=channel_id,
            media_type=item.media_type.value,
            mime_type=metadata.get("mime_type") or metadata.get("content_type"),
            file_name=metadata.get("file_name") or metadata.get("filename"),
            duration_ms=_duration_ms(metadata),
            external_attachment_id=external_id,
            source_url=item.url,
            storage_key=metadata.get("storage_key"),
            metadata_=metadata,
        )
        db.add(row)
        db.flush()
        persisted.append(row)
    return persisted
