"""Facebook Messenger webhook adapter."""

from typing import Any

from app.contracts.channel_event import ChannelProvider, NormalizedChannelEvent
from app.integrations._meta import parse_meta_events


class FacebookAdapter:
    def verify_webhook(self, payload: bytes, headers: dict[str, str]) -> bool:
        from app.core.config import settings
        from app.tenancy.webhook import verify_meta_signature
        return verify_meta_signature(payload, headers.get("x-hub-signature-256"), settings.META_APP_SECRET)

    def parse_events(self, payload: dict[str, Any]) -> list[NormalizedChannelEvent]:
        return parse_meta_events(payload, ChannelProvider.FACEBOOK)

    def send_message(self, *, recipient_external_id: str, text: str, access_token: str) -> dict[str, Any]:
        raise NotImplementedError("Use tenant-aware outbound service with db/business_id")

    def download_attachment(self, *, attachment_url: str, access_token: str) -> bytes:
        raise NotImplementedError
