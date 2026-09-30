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
        self.assertEqual("An", event.messages[0].metadata["display_name"])
        self.assertIsNone(event.messages[0].metadata["username"])

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
    def test_fetch_profile_avatar_uses_largest_profile_photo(self, post):
        photos_response = unittest.mock.Mock()
        photos_response.json.return_value = {
            "ok": True,
            "result": {
                "total_count": 1,
                "photos": [[
                    {"file_id": "avatar-small", "width": 40, "height": 40},
                    {"file_id": "avatar-large", "width": 160, "height": 160},
                ]],
            },
        }
        file_response = unittest.mock.Mock()
        file_response.json.return_value = {
            "ok": True,
            "result": {"file_path": "photos/avatar-large.jpg"},
        }
        post.side_effect = [photos_response, file_response]

        path = TelegramAdapter().fetch_profile_avatar_file_path(
            user_id="123",
            access_token="bot-token",
        )

        self.assertEqual("photos/avatar-large.jpg", path)
        self.assertEqual(2, post.call_count)
        self.assertIn("/getUserProfilePhotos", post.call_args_list[0].args[0])
        self.assertEqual(
            {"user_id": 123, "limit": 1},
            post.call_args_list[0].kwargs["json"],
        )
        self.assertIn("/getFile", post.call_args_list[1].args[0])
        self.assertEqual(
            {"file_id": "avatar-large"},
            post.call_args_list[1].kwargs["json"],
        )

    @patch("app.integrations.telegram.httpx.post")
    def test_fetch_profile_avatar_returns_none_when_user_has_no_photo(self, post):
        response = unittest.mock.Mock()
        response.json.return_value = {
            "ok": True,
            "result": {"total_count": 0, "photos": []},
        }
        post.return_value = response

        self.assertIsNone(
            TelegramAdapter().fetch_profile_avatar_file_path(
                user_id="123",
                access_token="bot-token",
            )
        )
        post.assert_called_once()

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
