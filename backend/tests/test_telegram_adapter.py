import unittest
from unittest.mock import patch

from app.integrations.telegram import TelegramAdapter


class TelegramAdapterTests(unittest.TestCase):
    def test_text_update_is_normalized_with_channel_account(self):
        payload = {
            "update_id": 9001,
            "message": {
                "message_id": 17,
                "date": 1700000000,
                "from": {"id": 123, "first_name": "An"},
                "chat": {"id": 123, "type": "private"},
                "text": "Cho hỏi giá sản phẩm?",
            },
        }

        events = TelegramAdapter().parse_events(payload, external_account_id="bot-1")

        self.assertEqual(1, len(events))
        event = events[0]
        self.assertEqual("bot-1", event.external_account_id)
        self.assertEqual("telegram:9001:17", event.external_event_id)
        self.assertEqual("123", event.messages[0].sender_external_id)
        self.assertEqual("Cho hỏi giá sản phẩm?", event.messages[0].text)

    def test_duplicate_update_is_not_emitted_twice(self):
        payload = {
            "update_id": 9002,
            "message": {
                "message_id": 18,
                "from": {"id": 123},
                "chat": {"id": 123},
                "text": "hello",
            },
        }

        events = TelegramAdapter().parse_events(payload, external_account_id="bot-1")
        self.assertEqual(1, len(events))
        self.assertEqual(events[0].external_event_id, events[0].messages[0].external_message_id)

    def test_update_without_message_is_ignored(self):
        self.assertEqual([], TelegramAdapter().parse_events({"update_id": 9003}, external_account_id="bot-1"))

    def test_audio_and_sticker_are_preserved_together(self):
        payload = {
            "update_id": 9004,
            "message": {
                "message_id": 19,
                "from": {"id": 123},
                "chat": {"id": 123},
                "audio": {"file_id": "audio-1", "duration": 4, "mime_type": "audio/ogg"},
                "sticker": {"file_id": "sticker-1", "emoji": "😀"},
            },
        }

        event = TelegramAdapter().parse_events(payload, external_account_id="bot-1")[0]

        self.assertEqual(["audio", "sticker"], [item.media_type.value for item in event.messages[0].attachments])
        self.assertEqual("audio-1", event.messages[0].attachments[0].external_attachment_id)
        self.assertEqual("sticker-1", event.messages[0].attachments[1].external_attachment_id)

    @patch("app.integrations.telegram.httpx.post")
    def test_send_media_maps_audio_to_send_audio(self, post):
        post.return_value.json.return_value = {"ok": True, "result": {"message_id": 20}}
        post.return_value.raise_for_status.return_value = None
        result = TelegramAdapter().send_media(
            recipient_external_id="123",
            media_type="audio",
            media_url="https://cdn.example/audio.mp3",
            caption="Nghe thử",
            access_token="token",
        )
        self.assertTrue(result["ok"])
        post.assert_called_once()
        self.assertIn("/sendAudio", post.call_args.args[0])
        self.assertEqual("https://cdn.example/audio.mp3", post.call_args.kwargs["json"]["audio"])


if __name__ == "__main__":
    unittest.main()
