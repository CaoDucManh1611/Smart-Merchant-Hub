import base64
from io import BytesIO
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

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
            zalo_oa_channel = Channel(
                business_id=business.id,
                channel_type="zalo",
                name="Zalo OA",
                external_account_id="zalo-oa-upload",
                config={"provider": "oa"},
            )
            tiktok_channel = Channel(
                business_id=business.id,
                channel_type="tiktok",
                name="TikTok",
                external_account_id="tiktok-upload",
                status="active",
            )
            shopee_channel = Channel(
                business_id=business.id,
                channel_type="shopee",
                name="Shopee",
                external_account_id="shopee-upload",
                status="active",
                config={"provider": "shopee_local_connector"},
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
            zalo_oa_customer = Customer(
                business_id=business.id,
                channel="zalo",
                external_user_id="zalo-oa-user-upload",
            )
            tiktok_customer = Customer(
                business_id=business.id,
                channel="tiktok",
                external_user_id="tiktok-user-upload",
            )
            shopee_customer = Customer(
                business_id=business.id,
                channel="shopee",
                external_user_id="shopee-user-upload",
            )
            db.add_all([channel, zalo_channel, zalo_oa_channel, tiktok_channel, shopee_channel, customer, zalo_customer, zalo_oa_customer, tiktok_customer, shopee_customer])
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
            zalo_oa_conversation = Conversation(
                business_id=business.id,
                customer_id=zalo_oa_customer.id,
                channel_id=zalo_oa_channel.id,
                channel="zalo",
            )
            tiktok_conversation = Conversation(
                business_id=business.id,
                customer_id=tiktok_customer.id,
                channel_id=tiktok_channel.id,
                channel="tiktok",
            )
            shopee_conversation = Conversation(
                business_id=business.id,
                customer_id=shopee_customer.id,
                channel_id=shopee_channel.id,
                channel="shopee",
            )
            db.add_all([conversation, zalo_conversation, zalo_oa_conversation, tiktok_conversation, shopee_conversation])
            db.commit()
            cls.conversation_id = conversation.id
            cls.zalo_conversation_id = zalo_conversation.id
            cls.zalo_oa_conversation_id = zalo_oa_conversation.id
            cls.tiktok_conversation_id = tiktok_conversation.id
            cls.shopee_conversation_id = shopee_conversation.id

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
                data={"media_type": "audio", "caption": "Nghe thử", "client_id": "media-audio-1"},
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
                data={"media_type": "audio", "client_id": "media-audio-2"},
            )

        self.assertEqual(200, response.status_code, response.text)
        normalize_audio.assert_called_once()
        self.assertTrue(response.json()["upload"]["media_url"].endswith(".aac"))
        self.assertEqual("audio/aac", response.json()["upload"]["content_type"])
        send_media.assert_called_once()
        self.assertTrue(send_media.call_args.kwargs["media_url"].endswith(".aac"))

    def test_telegram_voice_recording_is_normalized_then_uploaded_as_voice_note(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            conversations_api, "UPLOAD_DIR", Path(directory)
        ), patch(
            "app.api.conversations.normalize_telegram_voice_upload", create=True
        ) as normalize_voice, patch(
            "app.api.conversations.send_telegram_media",
            return_value={"ok": True, "result": {"message_id": 502}},
        ) as send_media:
            normalized_path = Path(directory) / "voice.ogg"
            normalized_path.write_bytes(b"ogg-opus-voice")
            normalize_voice.return_value = (normalized_path, "audio/ogg")
            response = self.client.post(
                f"/api/conversations/{self.conversation_id}/media/upload-generic",
                headers={"X-Business-Id": "1"},
                files={"file": ("voice.webm", b"webm-audio", "audio/webm;codecs=opus")},
                data={"media_type": "audio", "is_voice_note": "true", "client_id": "telegram-voice-1"},
            )

        self.assertEqual(200, response.status_code, response.text)
        normalize_voice.assert_called_once()
        self.assertEqual("audio/ogg", send_media.call_args.kwargs["upload_content_type"])
        self.assertEqual(b"ogg-opus-voice", send_media.call_args.kwargs["upload_bytes"])
        self.assertTrue(send_media.call_args.kwargs["voice_note"])

    def test_media_type_not_supported_by_channel_is_rejected_before_upload(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            conversations_api, "UPLOAD_DIR", Path(directory)
        ), patch("app.api.conversations.send_telegram_media") as send_media:
            response = self.client.post(
                f"/api/conversations/{self.zalo_oa_conversation_id}/media/upload-generic",
                headers={"X-Business-Id": "1"},
                files={"file": ("voice.ogg", b"ogg-opus", "audio/ogg")},
                data={"media_type": "audio", "client_id": "zalo-oa-audio-1"},
            )
            self.assertEqual(422, response.status_code, response.text)
            self.assertIn("Zalo OA", response.text)
            send_media.assert_not_called()
            self.assertEqual([], list(Path(directory).iterdir()))

    def test_tiktok_image_upload_forwards_bytes_to_local_connector(self):
        image = BytesIO()
        Image.new("RGB", (40, 40), "teal").save(image, "PNG")
        with tempfile.TemporaryDirectory() as directory, patch.object(
            conversations_api, "UPLOAD_DIR", Path(directory)
        ), patch.object(
            conversations_api,
            "send_tiktok_text",
            return_value=({"status": "sent", "message_id": "tiktok:image-1"}, None),
        ) as send_media:
            response = self.client.post(
                f"/api/conversations/{self.tiktok_conversation_id}/media/upload-generic",
                headers={"X-Business-Id": "1"},
                files={"file": ("photo.png", image.getvalue(), "image/png")},
                data={"media_type": "image", "caption": "Ảnh xem thử", "client_id": "tiktok-image-1"},
            )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("image", response.json()["message_type"])
        payload = send_media.call_args.kwargs["media_payload"]
        self.assertEqual("image", payload["mediaType"])
        self.assertEqual("image/png", payload["contentType"])
        self.assertEqual(image.getvalue(), base64.b64decode(payload["mediaData"]))

    def test_shopee_sticker_upload_forwards_png_artwork_to_local_connector(self):
        image = BytesIO()
        Image.new("RGBA", (40, 40), (20, 160, 150, 100)).save(image, "PNG")
        with tempfile.TemporaryDirectory() as directory, patch.object(
            conversations_api, "UPLOAD_DIR", Path(directory)
        ), patch.object(
            conversations_api,
            "send_shopee_text",
            return_value=({"status": "sent", "message_id": "shopee:sticker-1"}, None),
        ) as send_media:
            response = self.client.post(
                f"/api/conversations/{self.shopee_conversation_id}/media/upload-generic",
                headers={"X-Business-Id": "1"},
                files={"file": ("sticker.png", image.getvalue(), "image/png")},
                data={"media_type": "sticker", "caption": "", "client_id": "shopee-sticker-1"},
            )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("sticker", response.json()["message_type"])
        payload = send_media.call_args.kwargs["media_payload"]
        self.assertEqual("sticker", payload["mediaType"])
        self.assertEqual("image/png", payload["contentType"])
        self.assertEqual(image.getvalue(), base64.b64decode(payload["mediaData"]))

    def test_tiktok_audio_is_rejected_with_supported_image_types(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            conversations_api, "UPLOAD_DIR", Path(directory)
        ):
            response = self.client.post(
                f"/api/conversations/{self.tiktok_conversation_id}/media/upload-generic",
                headers={"X-Business-Id": "1"},
                files={"file": ("voice.mp3", b"audio-bytes", "audio/mpeg")},
                data={"media_type": "audio", "client_id": "tiktok-audio-1"},
            )

        self.assertEqual(422, response.status_code, response.text)
        self.assertIn("image, sticker", response.text)

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

    def test_public_image_error_explains_offline_ngrok_tunnel(self):
        import httpx
        from fastapi import HTTPException

        request = httpx.Request("GET", "https://public.example/image.jpg")
        response = httpx.Response(
            404,
            headers={"content-type": "text/html", "ngrok-error-code": "ERR_NGROK_3200"},
            request=request,
        )
        with patch("app.api.conversations.httpx.get", return_value=response):
            with self.assertRaises(HTTPException) as raised:
                conversations_api.check_public_image_url("https://public.example/image.jpg")

        self.assertEqual(400, raised.exception.status_code)
        self.assertEqual("ERR_NGROK_3200", raised.exception.detail["upstream_error_code"])
        self.assertIn("cổng 8000", raised.exception.detail["message"])

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
                data={"client_id": "zalo-image-1"},
            )

        self.assertEqual(200, response.status_code, response.text)
        send_media.assert_called_once()
        self.assertEqual("image", response.json()["media_type"])


    def test_meta_image_uploads_use_paired_connector_for_all_composer_routes(self):
        image = BytesIO()
        Image.new("RGB", (80, 80), "teal").save(image, "PNG")
        for channel_type in ("facebook", "instagram"):
            with Session(self.engine) as db:
                channel = Channel(
                    business_id=1, channel_type=channel_type, name=channel_type,
                    external_account_id=f"{channel_type}-image-test", status="active",
                    access_token_encrypted="encrypted-connector-token",
                    config={"provider": f"{channel_type}_local_connector"},
                )
                customer = Customer(business_id=1, channel=channel_type, external_user_id=f"buyer-{channel_type}")
                db.add_all([channel, customer])
                db.flush()
                conversation = Conversation(business_id=1, customer_id=customer.id, channel_id=channel.id, channel=channel_type)
                db.add(conversation)
                db.commit()
                conversation_id = conversation.id

            for route in ("send", "media/upload", "media/upload-generic"):
                with self.subTest(channel=channel_type, route=route), tempfile.TemporaryDirectory() as directory, patch.object(
                    conversations_api, "UPLOAD_DIR", Path(directory)
                ), patch.object(conversations_api, "check_public_image_url_async"), patch.object(
                    conversations_api, "check_public_image_url"
                ), patch.object(conversations_api, "decrypt_token", return_value="connector-token"), patch.object(
                    conversations_api, "_local_connector_thread_id", return_value="thread-1"
                ), patch.object(conversations_api.httpx, "post", return_value=Mock(
                    status_code=200, json=lambda: {"status": "sent", "message_id": f"{channel_type}:{route}"}
                )) as post, patch.object(conversations_api, "send_facebook_media") as facebook_graph, patch.object(
                    conversations_api, "send_instagram_media"
                ) as instagram_graph, patch.object(conversations_api, "send_facebook_image") as facebook_image, patch.object(
                    conversations_api, "send_instagram_image"
                ) as instagram_image:
                    response = self.client.post(
                        f"/api/conversations/{conversation_id}/{route}",
                        headers={"X-Business-Id": "1"},
                        files={"file": ("photo.png", image.getvalue(), "image/png")},
                        data={"client_id": f"meta-image-{channel_type}-{route.replace('/', '-')}", "media_type": "image"},
                    )
                    self.assertEqual(200, response.status_code, response.text)
                    post.assert_called_once()
                    payload = post.call_args.kwargs["json"]
                    self.assertEqual("image", payload["mediaType"])
                    self.assertEqual("thread-1", payload["threadId"])
                    self.assertEqual("", payload["message"])
                    self.assertTrue(base64.b64decode(payload["imageData"]).startswith(b"\xff\xd8\xff"))
                    self.assertEqual("connector-token", post.call_args.kwargs["headers"]["X-Meta-Bridge-Secret"])
                    for graph_sender in (facebook_graph, instagram_graph, facebook_image, instagram_image):
                        graph_sender.assert_not_called()
                    self.assertTrue(response.json()["messages"] if route == "send" else response.json()["message"])

    def test_meta_audio_upload_is_sent_through_local_connector_without_public_url(self):
        with Session(self.engine) as db:
            channel = Channel(
                business_id=1, channel_type="facebook", name="Facebook local audio",
                external_account_id="facebook-audio-test", status="active",
                access_token_encrypted="encrypted-connector-token",
                config={"provider": "facebook_local_connector"},
            )
            customer = Customer(business_id=1, channel="facebook", external_user_id="buyer-facebook-audio")
            db.add_all([channel, customer])
            db.flush()
            conversation = Conversation(
                business_id=1, customer_id=customer.id, channel_id=channel.id, channel="facebook"
            )
            db.add(conversation)
            db.commit()
            conversation_id = conversation.id

        audio = b"test-mp3-audio-bytes"
        with tempfile.TemporaryDirectory() as directory, patch.object(
            conversations_api, "UPLOAD_DIR", Path(directory)
        ), patch.object(conversations_api, "decrypt_token", return_value="connector-token"), patch.object(
            conversations_api, "_local_connector_thread_id", return_value="thread-audio"
        ), patch.object(conversations_api.httpx, "post", return_value=Mock(
            status_code=200, json=lambda: {"status": "sent", "message_id": "facebook:audio-1"}
        )) as post:
            response = self.client.post(
                f"/api/conversations/{conversation_id}/media/upload-generic",
                headers={"X-Business-Id": "1"},
                files={"file": ("voice.mp3", audio, "audio/mpeg")},
                data={"media_type": "audio", "caption": "Lời nhắn", "client_id": "facebook-audio-1"},
            )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("audio", response.json()["message_type"])
        payload = post.call_args.kwargs["json"]
        self.assertEqual("audio", payload["mediaType"])
        self.assertEqual("audio/mpeg", payload["contentType"])
        self.assertEqual(audio, base64.b64decode(payload["mediaData"]))
        self.assertEqual("Lời nhắn", payload["message"])


if __name__ == "__main__":
    unittest.main()
