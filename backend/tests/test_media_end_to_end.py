import unittest

from app.contracts.channel_event import ChannelProvider
from app.integrations._meta import parse_meta_events
from app.integrations.telegram import TelegramAdapter
from app.integrations.zalo import ZaloAdapter
from app.main import app


class MediaEndToEndContractTests(unittest.TestCase):
    def test_media_proxy_and_outbound_media_routes_are_registered(self):
        paths = set(app.openapi()["paths"])
        self.assertIn("/api/media/{attachment_id}", paths)
        self.assertIn("/api/conversations/{conversation_id}/send-media", paths)

    def test_each_provider_emits_canonical_media(self):
        meta = parse_meta_events(
            {
                "entry": [{
                    "id": "page-1",
                    "messaging": [{
                        "sender": {"id": "user-1"},
                        "message": {
                            "mid": "meta-media-1",
                            "attachments": [{"type": "audio", "payload": {"url": "https://cdn/audio.ogg"}}],
                        },
                    }],
                }],
            },
            ChannelProvider.FACEBOOK,
        )[0]
        telegram = TelegramAdapter().parse_events(
            {
                "update_id": 1,
                "message": {
                    "message_id": 1,
                    "from": {"id": 2},
                    "chat": {"id": 2},
                    "sticker": {"file_id": "sticker-1"},
                },
            },
            external_account_id="bot-1",
        )[0]
        zalo = ZaloAdapter().parse_events(
            {
                "event_name": "message.image.received",
                "message": {
                    "message_id": "z1",
                    "from": {"id": "u1"},
                    "chat": {"id": "u1"},
                    "photo_url": "https://cdn/photo.jpg",
                },
            },
            external_account_id="zalo-1",
        )[0]
        self.assertEqual("audio", meta.messages[0].attachments[0].media_type.value)
        self.assertEqual("sticker", telegram.messages[0].attachments[0].media_type.value)
        self.assertEqual("image", zalo.messages[0].attachments[0].media_type.value)


if __name__ == "__main__":
    unittest.main()
