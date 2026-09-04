"""Stable data contracts shared by channel integrations and CRM services."""

from app.contracts.channel_event import (
    ChannelProvider,
    MediaType,
    MessageDirection,
    NormalizedAttachment,
    NormalizedChannelEvent,
    NormalizedMessage,
    unique_channel_events,
    bind_event_to_channel,
)

__all__ = [
    "ChannelProvider",
    "MediaType",
    "MessageDirection",
    "NormalizedAttachment",
    "NormalizedChannelEvent",
    "NormalizedMessage",
    "unique_channel_events",
    "bind_event_to_channel",
]
