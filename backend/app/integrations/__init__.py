"""Provider adapters that translate external payloads into CRM contracts."""

from app.integrations.facebook import FacebookAdapter
from app.integrations.instagram import InstagramAdapter
from app.integrations.base import ChannelAdapter
from app.integrations.telegram import TelegramAdapter
from app.integrations.zalo import ZaloAdapter


def get_channel_adapter(provider: str) -> ChannelAdapter:
    """Return the canonical adapter for a provider name.

    Keeping provider selection in one place prevents webhook routes and
    background jobs from importing provider-specific classes directly.  The
    registry intentionally rejects unknown providers instead of silently
    falling back to a default adapter.
    """
    adapters = {
        "facebook": FacebookAdapter,
        "instagram": InstagramAdapter,
        "telegram": TelegramAdapter,
        "zalo": ZaloAdapter,
    }
    try:
        return adapters[provider.strip().lower()]()
    except (AttributeError, KeyError) as exc:
        raise ValueError(f"Unsupported channel provider: {provider}") from exc


__all__ = [
    "FacebookAdapter",
    "InstagramAdapter",
    "TelegramAdapter",
    "ZaloAdapter",
    "get_channel_adapter",
]
