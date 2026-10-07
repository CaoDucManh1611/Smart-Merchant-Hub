"""Outbound media types accepted by the channel adapters."""


OUTBOUND_MEDIA_TYPES = {
    "facebook": frozenset({"image", "audio", "video", "file"}),
    "instagram": frozenset({"image", "audio", "video", "file"}),
    "telegram": frozenset({"image", "audio", "video", "file", "sticker"}),
    "tiktok": frozenset(),
    "shopee": frozenset(),
}


def supported_outbound_media_types(channel: str, provider: str | None = None) -> frozenset[str]:
    channel = str(channel or "").strip().lower()
    if channel != "zalo":
        return OUTBOUND_MEDIA_TYPES.get(channel, frozenset())
    if str(provider or "bot").strip().lower() in {"oa", "zalo_oa", "official_account"}:
        return frozenset({"image"})
    return frozenset({"image", "audio", "sticker"})


def unsupported_media_detail(channel: str, media_type: str, provider: str | None = None) -> str | None:
    supported = supported_outbound_media_types(channel, provider)
    if str(media_type or "").strip().lower() in supported:
        return None
    channel_name = "Zalo OA" if channel == "zalo" and provider in {"oa", "zalo_oa", "official_account"} else str(channel or "Kênh này").title()
    supported_labels = ", ".join(sorted(supported))
    if not supported_labels:
        return f"{channel_name} hiện chỉ gửi được tin nhắn văn bản từ CRM."
    return f"{channel_name} chưa hỗ trợ gửi {media_type}. Hiện có thể gửi: {supported_labels}."
