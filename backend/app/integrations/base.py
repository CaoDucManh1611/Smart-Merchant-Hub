"""Interface implemented by every external messaging provider."""

from typing import Any, Protocol

from app.contracts.channel_event import NormalizedChannelEvent


class ChannelAdapter(Protocol):
    def verify_webhook(self, payload: bytes, headers: dict[str, str]) -> bool:
        """Verify provider authenticity before parsing."""

    def parse_events(self, payload: dict[str, Any], **context: Any) -> list[NormalizedChannelEvent]:
        """Translate one webhook payload into zero or more canonical events."""

    def send_message(self, *, recipient_external_id: str, text: str, access_token: str) -> dict[str, Any]:
        """Send with credentials resolved from a tenant-owned Channel."""

    def download_attachment(self, *, attachment_url: str, access_token: str) -> bytes:
        """Download media with credentials resolved from a tenant-owned Channel."""
