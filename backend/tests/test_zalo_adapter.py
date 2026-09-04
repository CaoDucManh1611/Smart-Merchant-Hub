import unittest
from unittest.mock import patch

from app.integrations.zalo import ZaloAdapter


class ZaloAdapterTests(unittest.TestCase):
    def test_text_event_is_normalized_with_bot_account_and_chat_id(self):
        payload = {
            "event_name": "message.text.received",
            "message": {
                "message_id": "z-msg-1",
                "date": 1775362520302,
                "chat": {"id": "z-chat-1", "chat_type": "PRIVATE"},
                "from": {"id": "z-user-1", "display_name": "Zalo Buyer", "is_bot": False},
                "text": "Cho hỏi giá sản phẩm?",
            },
        }

        events = ZaloAdapter().parse_events(payload, external_account_id="zalo-bot-1")

        self.assertEqual(1, len(events))
        event = events[0]
        self.assertEqual("zalo", event.provider.value)
        self.assertEqual("zalo:zalo-bot-1:z-msg-1", event.external_event_id)
        self.assertEqual("z-user-1", event.messages[0].sender_external_id)
        self.assertEqual("z-chat-1", event.messages[0].metadata["chat_id"])
        self.assertEqual("Cho hỏi giá sản phẩm?", event.messages[0].text)

    def test_image_event_is_normalized_with_photo_attachment(self):
        payload = {
            "event_name": "message.image.received",
            "message": {
                "message_id": "z-img-1",
                "date": 1775362520302,
                "chat": {"id": "z-chat-1", "chat_type": "PRIVATE"},
                "from": {"id": "z-user-1", "display_name": "Zalo Buyer"},
                "photo_url": "https://example.com/photo.jpg",
            },
        }

        event = ZaloAdapter().parse_events(payload, external_account_id="zalo-bot-1")[0]

        self.assertEqual("image", event.messages[0].message_type.value)
        self.assertEqual("https://example.com/photo.jpg", event.messages[0].attachments[0].url)

    def test_bot_message_and_missing_message_are_ignored(self):
        bot_payload = {
            "event_name": "message.text.received",
            "message": {
                "message_id": "z-bot-1",
                "chat": {"id": "z-chat-1"},
                "from": {"id": "z-bot-1", "is_bot": True},
                "text": "echo",
            },
        }
        self.assertEqual([], ZaloAdapter().parse_events(bot_payload, external_account_id="zalo-bot-1"))
        self.assertEqual([], ZaloAdapter().parse_events({"event_name": "follow"}, external_account_id="zalo-bot-1"))

    def test_audio_and_sticker_variants_are_normalized_together(self):
        payload = {
            "event_name": "message.media.received",
            "message": {
                "message_id": "z-media-1",
                "chat": {"id": "z-chat-1"},
                "from": {"id": "z-user-1", "is_bot": False},
                "audio": {"url": "https://example.com/audio.mp3", "duration": 2},
                "sticker": {"url": "https://example.com/sticker.webp", "id": "stk-1"},
            },
        }

        event = ZaloAdapter().parse_events(payload, external_account_id="zalo-bot-1")[0]

        self.assertEqual(["audio", "sticker"], [item.media_type.value for item in event.messages[0].attachments])

    def test_flat_zalo_media_fields_are_normalized(self):
        """Accept the type/url shape used by Zalo conversation APIs and bridges."""
        payload = {
            "event_name": "message.photo.received",
            "message": {
                "message_id": "z-flat-photo-1",
                "date": 1775362520302,
                "chat": {"id": "z-chat-1", "chat_type": "PRIVATE"},
                "from": {"id": "z-user-1", "display_name": "Zalo Buyer"},
                "type": "photo",
                "url": "https://example.com/zalo-photo.jpg",
                "thumb": "https://example.com/zalo-photo-thumb.jpg",
                "message": "Ảnh sản phẩm",
            },
        }

        event = ZaloAdapter().parse_events(payload, external_account_id="zalo-bot-1")[0]

        self.assertEqual("Ảnh sản phẩm", event.messages[0].text)
        self.assertEqual("image", event.messages[0].message_type.value)
        self.assertEqual("https://example.com/zalo-photo.jpg", event.messages[0].attachments[0].url)
        self.assertEqual(
            "https://example.com/zalo-photo-thumb.jpg",
            event.messages[0].attachments[0].metadata["thumb_url"],
        )

    def test_nested_attachments_and_voice_type_are_normalized(self):
        payload = {
            "event_name": "message.voice.received",
            "message": {
                "message_id": "z-flat-voice-1",
                "chat": {"id": "z-chat-1"},
                "from": {"id": "z-user-1", "is_bot": False},
                "type": "voice",
                "url": "https://example.com/zalo-voice.ogg",
                "attachments": [
                    {"type": "sticker", "payload": {"url": "https://example.com/s.webp"}},
                ],
            },
        }

        event = ZaloAdapter().parse_events(payload, external_account_id="zalo-bot-1")[0]

        self.assertEqual(
            ["audio", "sticker"],
            [item.media_type.value for item in event.messages[0].attachments],
        )
        self.assertEqual("https://example.com/zalo-voice.ogg", event.messages[0].attachments[0].url)

    @patch("app.integrations.zalo.httpx.post")
    def test_send_media_maps_image_to_send_photo(self, post):
        post.return_value.json.return_value = {"ok": True, "result": {"message_id": "z-out-1"}}
        post.return_value.raise_for_status.return_value = None
        result = ZaloAdapter().send_media(
            recipient_external_id="z-user-1",
            media_type="image",
            media_url="https://cdn.example/photo.jpg",
            caption="Ảnh sản phẩm",
            access_token="token",
        )
        self.assertTrue(result["ok"])
        self.assertIn("/sendPhoto", post.call_args.args[0])
        self.assertEqual("https://cdn.example/photo.jpg", post.call_args.kwargs["json"]["photo"])


if __name__ == "__main__":
    unittest.main()
