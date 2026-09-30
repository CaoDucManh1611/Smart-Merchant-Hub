"""Canonical, provider-independent contracts for inbound channel events."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChannelProvider(str, Enum):
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    TELEGRAM = "telegram"
    ZALO = "zalo"


class MessageDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MediaType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"
    STICKER = "sticker"
    UNKNOWN = "unknown"


class NormalizedAttachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_type: MediaType
    url: str | None = None
    external_attachment_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_message_id: str = Field(min_length=1)
    direction: MessageDirection
    message_type: MediaType
    text: str | None = None
    attachments: list[NormalizedAttachment] = Field(default_factory=list)
    sender_external_id: str = Field(min_length=1)
    reply_to_external_message_id: str | None = None
    provider_created_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedChannelEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    provider: ChannelProvider
    external_event_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    external_account_id: str = Field(min_length=1)
    sender_external_id: str | None = None
    recipient_external_id: str | None = None
    provider_created_at: datetime | None = None
    channel_id: int | None = None
    business_id: int | None = None
    raw_payload: dict[str, Any]
    messages: list[NormalizedMessage] = Field(default_factory=list)


def unique_channel_events(
    events: list[NormalizedChannelEvent],
) -> list[NormalizedChannelEvent]:
    """Keep the first copy of each provider/account/event combination."""

    unique: list[NormalizedChannelEvent] = []
    seen: set[tuple[ChannelProvider, str, str]] = set()

    for event in events:
        identity = (
            event.provider,
            event.external_account_id,
            event.external_event_id,
        )
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(event)

    return unique


def bind_event_to_channel(event: NormalizedChannelEvent, *, channel_id: int, business_id: int) -> NormalizedChannelEvent:
    """Attach trusted ownership after resolving the external account."""
    if channel_id <= 0 or business_id <= 0:
        raise ValueError("channel_id and business_id must be positive")
    return event.model_copy(update={"channel_id": channel_id, "business_id": business_id})
