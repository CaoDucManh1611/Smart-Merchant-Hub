import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api import conversations as conversations_api
from app.api.conversations import get_public_base_url
from app.core.config import settings
from app.db.dependencies import get_db
from app.main import app
from app.models import Business, Channel, Conversation, Customer, MessageAttachment


class MediaUploadApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Upload Shop", slug="upload-shop")
            db.add(business)
            db.flush()
            channel = Channel(
                business_id=business.id,
                channel_type="telegram",
                name="Telegram",
                external_account_id="bot-upload",
            )
            zalo_channel = Channel(
                business_id=business.id,
                channel_type="zalo",
                name="Zalo Bot",
                external_account_id="zalo-upload",
            )
            customer = Customer(
                business_id=business.id,
                channel="telegram",
                external_user_id="user-upload",
            )
            zalo_customer = Customer(
                business_id=business.id,
                channel="zalo",
                external_user_id="zalo-user-upload",
            )
            db.add_all([channel, zalo_channel, customer, zalo_customer])
            db.flush()
            conversation = Conversation(
                business_id=business.id,
                customer_id=customer.id,
                channel_id=channel.id,
                channel="telegram",
            )
            zalo_conversation = Conversation(
                business_id=business.id,
                customer_id=zalo_customer.id,
                channel_id=zalo_channel.id,
                channel="zalo",
            )
            db.add_all([conversation, zalo_conversation])
            db.commit()
            cls.conversation_id = conversation.id
            cls.zalo_conversation_id = zalo_conversation.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)
        cls.original_base_url = settings.PUBLIC_BASE_URL
        settings.PUBLIC_BASE_URL = "https://public.example"

    @classmethod
    def tearDownClass(cls):
        settings.PUBLIC_BASE_URL = cls.original_base_url
        app.dependency_overrides.clear()

    def test_upload_audio_uses_generic_media_route_and_persists_attachment(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            conversations_api, "UPLOAD_DIR", Path(directory)
        ), patch(
            "app.api.conversations.send_telegram_media",
            return_value={"ok": True, "result": {"message_id": 501}},
        ):
            response = self.client.post(
                f"/api/conversations/{self.conversation_id}/media/upload-generic",
                headers={"X-Business-Id": "1"},
                files={"file": ("voice.ogg", b"audio-bytes", "audio/ogg")},
                data={"media_type": "audio", "caption": "Nghe thử"},
            )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("audio", response.json()["message_type"])
        with Session(self.engine) as db:
            attachment = db.scalar(
                select(MessageAttachment).where(MessageAttachment.media_type == "audio")
            )
            self.assertIsNotNone(attachment)
            self.assertTrue(attachment.source_url.startswith("https://public.example/"))

    def test_zalo_audio_is_normalized_to_aac_before_delivery(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            conversations_api, "UPLOAD_DIR", Path(directory)
        ), patch(
            "app.api.conversations.normalize_zalo_audio_upload", create=True
        ) as normalize_audio, patch(
            "app.api.conversations.send_zalo_media",
            return_value={"ok": True, "message_id": "zalo:zalo-upload:voice-1"},
        ) as send_media:
            normalized_path = Path(directory) / "voice.aac"
            normalized_path.write_bytes(b"aac-audio")
            normalize_audio.return_value = (normalized_path, "audio/aac")
            response = self.client.post(
                f"/api/conversations/{self.zalo_conversation_id}/media/upload-generic",
                headers={"X-Business-Id": "1"},
                files={"file": ("voice.webm", b"webm-audio", "audio/webm")},
                data={"media_type": "audio"},
            )

        self.assertEqual(200, response.status_code, response.text)
        normalize_audio.assert_called_once()
        self.assertTrue(response.json()["upload"]["media_url"].endswith(".aac"))
        self.assertEqual("audio/aac", response.json()["upload"]["content_type"])
        send_media.assert_called_once()
        self.assertTrue(send_media.call_args.kwargs["media_url"].endswith(".aac"))

    def test_public_base_url_ignores_legacy_oauth_callback_path(self):
        previous_public_base_url = settings.PUBLIC_BASE_URL
        settings.PUBLIC_BASE_URL = (
            "https://vocalist-dreamy-corned.ngrok-free.dev/api/oauth/meta/callback"
        )
        try:
            self.assertEqual(
                "https://vocalist-dreamy-corned.ngrok-free.dev",
                get_public_base_url(),
            )
        finally:
            settings.PUBLIC_BASE_URL = previous_public_base_url

    def test_legacy_ui_image_upload_uses_zalo_media_sender(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            conversations_api, "UPLOAD_DIR", Path(directory)
        ), patch(
            "app.api.conversations.prepare_uploaded_image",
            return_value=("https://public.example/image.jpg", Path("image.jpg")),
        ), patch(
            "app.api.conversations.send_zalo_media",
            return_value={"ok": True, "message_id": "zalo:zalo-upload:image-1"},
        ) as send_media:
            response = self.client.post(
                f"/api/conversations/{self.zalo_conversation_id}/send",
                headers={"X-Business-Id": "1"},
                files={"file": ("image.jpg", b"not-used", "image/jpeg")},
            )

        self.assertEqual(200, response.status_code, response.text)
        send_media.assert_called_once()
        self.assertEqual("image", response.json()["media_type"])


if __name__ == "__main__":
    unittest.main()
