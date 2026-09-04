import unittest
from pathlib import Path
from unittest.mock import ANY, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.dependencies import get_db
from app.integrations.telegram import TelegramAdapter
from app.main import app
from app.models.business import Business
from app.models.channel import Channel
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.message import Message
from app.models.message_attachment import MessageAttachment
from app.services.channel_credentials import encrypt_token


class TelegramOutboundApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        settings.CHANNEL_ENCRYPTION_KEY = "telegram-outbound-test-key"
        with Session(cls.engine) as db:
            one = Business(name="Outbound One", slug="outbound-one")
            two = Business(name="Outbound Two", slug="outbound-two")
            db.add_all([one, two])
            db.flush()

            channel = Channel(
                business_id=one.id,
                channel_type="telegram",
                name="Shop Telegram",
                external_account_id="bot-1",
                access_token_encrypted=encrypt_token("secret-token", settings.CHANNEL_ENCRYPTION_KEY),
                status="active",
            )
            customer = Customer(
                business_id=one.id,
                channel="telegram",
                external_user_id="12345",
                name="Telegram Buyer",
            )
            other_customer = Customer(
                business_id=two.id,
                channel="telegram",
                external_user_id="98765",
                name="Other Buyer",
            )
            db.add_all([channel, customer, other_customer])
            db.flush()
            conversation = Conversation(
                business_id=one.id,
                customer_id=customer.id,
                channel_id=channel.id,
                channel="telegram",
            )
            other_conversation = Conversation(
                business_id=two.id,
                customer_id=other_customer.id,
                channel="telegram",
            )
            db.add_all([conversation, other_conversation])
            db.commit()
            cls.conversation_id = conversation.id
            cls.other_conversation_id = other_conversation.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_send_text_uses_tenant_channel_and_persists_outbound_message(self):
        calls = []

        def fake_send(self, *, recipient_external_id, text, access_token):
            calls.append((recipient_external_id, text, access_token))
            return {"ok": True, "result": {"message_id": 77}}

        with patch.object(TelegramAdapter, "send_message", fake_send):
            response = self.client.post(
                f"/api/conversations/{self.conversation_id}/send",
                headers={"X-Business-Id": "1"},
                data={"text": "Xin chào từ nhân viên"},
            )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual([("12345", "Xin chào từ nhân viên", "secret-token")], calls)
        body = response.json()
        self.assertEqual(["telegram:bot-1:77"], body["message_ids"])
        with Session(self.engine) as db:
            saved = db.scalar(
                select(Message).where(
                    Message.conversation_id == self.conversation_id,
                    Message.direction == "outbound",
                    Message.external_message_id == "telegram:bot-1:77",
                )
            )
            self.assertIsNotNone(saved)
            self.assertEqual("telegram", saved.channel)
            self.assertEqual("Xin chào từ nhân viên", saved.content)

    def test_cross_tenant_conversation_cannot_send(self):
        with patch.object(TelegramAdapter, "send_message") as send:
            response = self.client.post(
                f"/api/conversations/{self.other_conversation_id}/send",
                headers={"X-Business-Id": "1"},
                data={"text": "Không được gửi"},
            )
        self.assertEqual(404, response.status_code)
        send.assert_not_called()

    def test_telegram_conversation_without_channel_link_has_no_fallback(self):
        with Session(self.engine) as db:
            customer = Customer(
                business_id=1,
                channel="telegram",
                external_user_id="no-channel-user",
            )
            db.add(customer)
            db.flush()
            conversation = Conversation(
                business_id=1,
                customer_id=customer.id,
                channel="telegram",
                channel_id=None,
            )
            db.add(conversation)
            db.commit()
            conversation_id = conversation.id

        with patch.object(TelegramAdapter, "send_message") as send:
            response = self.client.post(
                f"/api/conversations/{conversation_id}/send",
                headers={"X-Business-Id": "1"},
                data={"text": "Không fallback token global"},
            )
        self.assertEqual(409, response.status_code)
        send.assert_not_called()

    def test_send_media_uses_tenant_channel_and_persists_attachment(self):
        with patch(
            "app.services.telegram_service.TelegramAdapter.send_media",
            return_value={"ok": True, "result": {"message_id": 78}},
        ) as send:
            response = self.client.post(
                f"/api/conversations/{self.conversation_id}/send-media",
                headers={"X-Business-Id": "1"},
                json={
                    "media_type": "audio",
                    "media_url": "https://cdn.example/audio.ogg",
                    "caption": "Nghe thử",
                },
            )

        self.assertEqual(200, response.status_code, response.text)
        send.assert_called_once()
        self.assertEqual("audio", response.json()["message_type"])
        with Session(self.engine) as db:
            saved = db.scalar(
                select(MessageAttachment).join(Message).where(
                    Message.conversation_id == self.conversation_id,
                    Message.direction == "outbound",
                    MessageAttachment.media_type == "audio",
                )
            )
            self.assertIsNotNone(saved)

    def test_legacy_ui_image_upload_uses_telegram_media_sender(self):
        """The composer image path must work for Telegram, not only Meta."""
        with patch(
            "app.api.conversations.prepare_uploaded_image",
            return_value=("https://cdn.example/image.jpg", Path("image.jpg")),
        ) as prepare, patch(
            "app.api.conversations.send_telegram_media",
            return_value={"ok": True, "message_id": "telegram:bot-1:image-1"},
        ) as send_media:
            response = self.client.post(
                f"/api/conversations/{self.conversation_id}/send",
                headers={"X-Business-Id": "1"},
                files={"file": ("image.jpg", b"not-used", "image/jpeg")},
            )

        self.assertEqual(200, response.status_code, response.text)
        prepare.assert_called_once()
        send_media.assert_called_once_with(
            db=ANY,
            business_id=1,
            conversation_id=self.conversation_id,
            recipient_id="12345",
            media_type="image",
            media_url="https://cdn.example/image.jpg",
            caption=None,
        )


if __name__ == "__main__":
    unittest.main()
