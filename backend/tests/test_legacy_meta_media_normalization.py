import unittest

from app.services.message_service import normalize_message


class LegacyMetaMediaNormalizationTests(unittest.TestCase):
    def test_facebook_legacy_path_preserves_all_media_attachments(self):
        normalized = normalize_message(
            "facebook",
            {
                "entry": [{
                    "id": "page-1",
                    "messaging": [{
                        "sender": {"id": "user-1"},
                        "recipient": {"id": "page-1"},
                        "message": {
                            "mid": "m-1",
                            "attachments": [
                                {"type": "image", "payload": {"url": "https://cdn/image.jpg"}},
                                {"type": "audio", "payload": {"url": "https://cdn/audio.ogg"}},
                            ],
                        },
                    }],
                }],
            },
        )
        self.assertEqual(["image", "audio"], [item["media_type"] for item in normalized["attachments"]])

    def test_instagram_legacy_path_preserves_sticker(self):
        normalized = normalize_message(
            "instagram",
            {
                "entry": [{
                    "id": "page-1",
                    "messaging": [{
                        "sender": {"id": "user-1"},
                        "recipient": {"id": "page-1"},
                        "message": {
                            "mid": "m-2",
                            "attachments": [{"type": "sticker", "payload": {"url": "https://cdn/sticker.webp"}}],
                        },
                    }],
                }],
            },
        )
        self.assertEqual("sticker", normalized["attachments"][0]["media_type"])


if __name__ == "__main__":
    unittest.main()
