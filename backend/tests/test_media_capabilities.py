from unittest.mock import Mock, patch

from app.integrations.telegram import TelegramAdapter
from app.services.media_capabilities import supported_outbound_media_types, unsupported_media_detail
from app.services.telegram_media import normalize_telegram_voice_upload


def test_channel_media_capabilities_match_the_outbound_adapters():
    assert supported_outbound_media_types("facebook") == {"image", "audio", "video", "file"}
    assert supported_outbound_media_types("instagram") == {"image", "audio", "video", "file"}
    assert supported_outbound_media_types("telegram") == {"image", "audio", "video", "file", "sticker"}
    assert supported_outbound_media_types("zalo", "bot") == {"image", "audio", "sticker"}
    assert supported_outbound_media_types("zalo", "oa") == {"image"}
    assert supported_outbound_media_types("tiktok") == set()
    assert "chỉ gửi được tin nhắn văn bản" in unsupported_media_detail("shopee", "image")
    assert "chưa hỗ trợ gửi audio" in unsupported_media_detail("zalo", "audio", "oa")


def test_telegram_voice_note_uses_send_voice_multipart_upload():
    response = Mock()
    response.json.return_value = {"ok": True, "result": {"message_id": 12}}
    with patch("app.integrations.telegram.httpx.post", return_value=response) as post:
        result = TelegramAdapter().send_media(
            recipient_external_id="123",
            media_type="audio",
            media_url="https://public.example/voice.ogg",
            access_token="bot-token",
            caption="Xin chào",
            upload_bytes=b"ogg-opus",
            upload_filename="voice.ogg",
            upload_content_type="audio/ogg",
            voice_note=True,
        )

    assert result["ok"] is True
    args, kwargs = post.call_args
    assert args[0].endswith("/sendVoice")
    assert kwargs["data"] == {"chat_id": "123", "caption": "Xin chào"}
    assert kwargs["files"] == {"voice": ("voice.ogg", b"ogg-opus", "audio/ogg")}
    assert "json" not in kwargs
    response.raise_for_status.assert_called_once()


def test_telegram_ogg_voice_is_not_transcoded_again(tmp_path):
    voice = tmp_path / "voice.ogg"
    voice.write_bytes(b"already-ogg-opus")

    normalized, content_type = normalize_telegram_voice_upload(voice, content_type="audio/ogg")

    assert normalized == voice
    assert content_type == "audio/ogg"
