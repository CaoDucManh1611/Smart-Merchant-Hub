import unittest

from app.contracts.channel_event import ChannelProvider
from app.integrations._meta import parse_meta_events


class MetaMediaContractTests(unittest.TestCase):
    def test_all_supported_media_aliases_are_normalized(self):
        payload = {
            "entry": [{
                "id": "page-1",
                "messaging": [{
                    "sender": {"id": "user-1"},
                    "recipient": {"id": "page-1"},
                    "timestamp": 1700000000000,
                    "message": {
                        "mid": "mid-media-1",
                        "attachments": [
                            {"type": "photo", "payload": {"url": "https://cdn/photo.jpg"}},
                            {"type": "audio", "payload": {"url": "https://cdn/audio.ogg"}},
                            {"type": "sticker", "payload": {"url": "https://cdn/sticker.webp"}},
                            {"type": "video", "payload": {"url": "https://cdn/video.mp4"}},
                            {"type": "file", "payload": {"url": "https://cdn/file.pdf"}},
                        ],
                    },
                }],
            }],
        }

        event = parse_meta_events(payload, ChannelProvider.FACEBOOK)[0]

        self.assertEqual(
            ["image", "audio", "sticker", "video", "file"],
            [item.media_type.value for item in event.messages[0].attachments],
        )


if __name__ == "__main__":
    unittest.main()
