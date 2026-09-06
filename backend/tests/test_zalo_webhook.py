import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models import Business, Channel, ChannelEvent, Conversation, Customer, CustomerIdentity, Message, MessageAttachment


class ZaloWebhookApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Zalo Shop", slug="zalo-shop")
            db.add(business)
            db.flush()
            db.add(
                Channel(
                    business_id=business.id,
                    channel_type="zalo",
                    name="Shop Zalo Bot",
                    external_account_id="zalo-bot-1",
                    status="active",
                    config={"webhook_secret": "zalo-secret-1"},
                )
            )
            db.commit()
            cls.business_id = business.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    @staticmethod
    def text_payload(message_id: str = "z-msg-1") -> dict:
        return {
            "event_name": "message.text.received",
            "message": {
                "message_id": message_id,
                "date": 1775362520302,
                "chat": {"id": "z-user-1", "chat_type": "PRIVATE"},
                "from": {
                    "id": "z-user-1",
                    "display_name": "Zalo Buyer",
                    "avatar_url": "https://cdn.example/zalo-avatar.jpg",
                    "is_bot": False,
                },
                "text": "Tôi muốn xem sản phẩm",
            },
        }

    def test_valid_secret_persists_zalo_message_under_channel_tenant(self):
        with patch(
            "app.services.customer_fact_extractor.process_customer_fact_extraction_background"
        ), patch("app.services.auto_reply_service.process_rag_auto_reply_background"):
            response = self.client.post(
                "/api/webhooks/zalo",
                headers={"X-Bot-Api-Secret-Token": "zalo-secret-1"},
                json=self.text_payload(),
            )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual({"status": "received", "processed": 1}, response.json())
        with Session(self.engine) as db:
            channel_event = db.scalar(select(ChannelEvent))
            self.assertIsNotNone(channel_event)
            customer = db.scalar(select(Customer).where(Customer.channel == "zalo"))
            self.assertIsNotNone(customer)
            self.assertEqual(self.business_id, customer.business_id)
            self.assertEqual("Zalo Buyer", customer.name)
            self.assertEqual("https://cdn.example/zalo-avatar.jpg", customer.avatar_url)
            identity = db.scalar(select(CustomerIdentity).where(CustomerIdentity.customer_id == customer.id))
            self.assertIsNotNone(identity)
            self.assertEqual("Zalo Buyer", identity.display_name)
            conversation = db.scalar(select(Conversation).where(Conversation.channel == "zalo"))
            self.assertIsNotNone(conversation)
            self.assertEqual(self.business_id, conversation.business_id)
            saved = db.scalar(select(Message).where(Message.channel == "zalo"))
            self.assertIsNotNone(saved)
            self.assertEqual("Tôi muốn xem sản phẩm", saved.content)

    def test_invalid_secret_is_rejected_before_persistence(self):
        response = self.client.post(
            "/api/webhooks/zalo",
            headers={"X-Bot-Api-Secret-Token": "wrong-secret"},
            json=self.text_payload("z-msg-invalid"),
        )

        self.assertEqual(401, response.status_code)

    def test_duplicate_zalo_delivery_is_acknowledged_without_duplicate_message(self):
        with patch(
            "app.services.customer_fact_extractor.process_customer_fact_extraction_background"
        ), patch("app.services.auto_reply_service.process_rag_auto_reply_background"):
            first = self.client.post(
                "/api/webhooks/zalo",
                headers={"X-Bot-Api-Secret-Token": "zalo-secret-1"},
                json=self.text_payload("z-msg-duplicate"),
            )
            second = self.client.post(
                "/api/webhooks/zalo",
                headers={"X-Bot-Api-Secret-Token": "zalo-secret-1"},
                json=self.text_payload("z-msg-duplicate"),
            )

        self.assertEqual(200, first.status_code, first.text)
        self.assertEqual(200, second.status_code, second.text)
        self.assertEqual(1, first.json()["processed"])
        self.assertEqual(0, second.json()["processed"])
        with Session(self.engine) as db:
            count = db.query(Message).filter(Message.external_message_id == "zalo:zalo-bot-1:z-msg-duplicate").count()
            self.assertEqual(1, count)

    def test_multi_media_update_persists_every_attachment(self):
        payload = self.text_payload("z-msg-media")
        payload["event_name"] = "message.media.received"
        payload["message"].update({
            "audio": {"url": "https://example.com/a.ogg", "duration": 4},
            "sticker": {"url": "https://example.com/s.webp", "id": "sticker-1"},
        })
        with patch(
            "app.services.customer_fact_extractor.process_customer_fact_extraction_background"
        ), patch("app.services.auto_reply_service.process_rag_auto_reply_background"):
            response = self.client.post(
                "/api/webhooks/zalo",
                headers={"X-Bot-Api-Secret-Token": "zalo-secret-1"},
                json=payload,
            )

        self.assertEqual(200, response.status_code, response.text)
        with Session(self.engine) as db:
            message = db.scalar(select(Message).where(Message.external_message_id == "zalo:zalo-bot-1:z-msg-media"))
            rows = db.scalars(
                select(MessageAttachment).where(MessageAttachment.message_id == message.id).order_by(MessageAttachment.id)
            ).all()
            self.assertEqual(["audio", "sticker"], [row.media_type for row in rows])


if __name__ == "__main__":
    unittest.main()
