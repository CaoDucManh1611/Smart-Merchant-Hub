import unittest
import hashlib
import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.core.config import settings
from app.models import Business, Channel, ChannelEvent, Conversation, Customer, CustomerIdentity, Message, MessageAttachment
from app.services.channel_credentials import encrypt_token


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
                    access_token_encrypted=encrypt_token(
                        "zalo-oa-access-token",
                        settings.CHANNEL_ENCRYPTION_KEY,
                    ),
                )
            )
            db.add(
                Channel(
                    business_id=business.id,
                    channel_type="zalo",
                    name="Shop Zalo OA",
                    external_account_id="zalo-oa-1",
                    status="active",
                    config={
                        "provider": "zalo_oa",
                        "oa_app_id": "oa-app-1",
                        "oa_id": "zalo-oa-1",
                        "oa_secret_key": "oa-secret-1",
                    },
                    access_token_encrypted=encrypt_token(
                        "zalo-oa-access-token",
                        settings.CHANNEL_ENCRYPTION_KEY,
                    ),
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

    @staticmethod
    def oa_text_payload(message_id: str = "oa-msg-1") -> dict:
        return {
            "app_id": "oa-app-1",
            "oa_id": "zalo-oa-1",
            "event_name": "user_send_text",
            "sender": {"id": "oa-user-1"},
            "recipient": {"id": "zalo-oa-1"},
            "message": {"text": "Xin chào OA", "msg_id": message_id},
            "timestamp": "1775362520302",
        }

    @staticmethod
    def oa_signature(payload: dict) -> tuple[str, bytes]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        timestamp = str(payload["timestamp"])
        raw = "oa-app-1".encode() + body + timestamp.encode() + b"oa-secret-1"
        digest = hashlib.sha256(raw).hexdigest()
        return f"mac={digest}", body

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

    def test_missing_webhook_avatar_is_enriched_from_zalo_profile(self):
        payload = self.text_payload("z-msg-profile")
        payload["message"]["from"].pop("avatar_url")
        with patch(
            "app.integrations.zalo.ZaloAdapter.fetch_user_profile",
            return_value={
                "display_name": "Zalo Buyer",
                "avatar_url": "https://cdn.example/zalo-profile.jpg",
            },
        ), patch(
            "app.services.customer_fact_extractor.process_customer_fact_extraction_background"
        ), patch("app.services.auto_reply_service.process_rag_auto_reply_background"):
            response = self.client.post(
                "/api/webhooks/zalo",
                headers={"X-Bot-Api-Secret-Token": "zalo-secret-1"},
                json=payload,
            )

        self.assertEqual(200, response.status_code, response.text)
        with Session(self.engine) as db:
            customer = db.scalar(
                select(Customer).where(Customer.external_user_id == "z-user-1")
            )
            self.assertEqual("https://cdn.example/zalo-profile.jpg", customer.avatar_url)

    def test_invalid_secret_is_rejected_before_persistence(self):
        response = self.client.post(
            "/api/webhooks/zalo",
            headers={"X-Bot-Api-Secret-Token": "wrong-secret"},
            json=self.text_payload("z-msg-invalid"),
        )

        self.assertEqual(401, response.status_code)

    def test_oa_webhook_signature_persists_message_and_returns_200(self):
        payload = self.oa_text_payload()
        signature, body = self.oa_signature(payload)
        with patch(
            "app.integrations.zalo.ZaloAdapter.fetch_user_profile",
            return_value={
                "display_name": "OA Buyer",
                "avatar_url": "https://cdn.example/oa-avatar.jpg",
            },
        ), patch(
            "app.services.customer_fact_extractor.process_customer_fact_extraction_background"
        ), patch("app.services.auto_reply_service.process_rag_auto_reply_background"):
            response = self.client.post(
                "/api/webhooks/zalo",
                headers={
                    "X-ZEvent-Signature": signature,
                    "Content-Type": "application/json",
                },
                content=body,
            )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual({"status": "received", "processed": 1}, response.json())
        with Session(self.engine) as db:
            customer = db.scalar(select(Customer).where(Customer.external_user_id == "oa-user-1"))
            self.assertIsNotNone(customer)
            self.assertEqual("OA Buyer", customer.name)
            self.assertEqual("https://cdn.example/oa-avatar.jpg", customer.avatar_url)
            saved = db.scalar(select(Message).where(Message.external_message_id == "zalo:zalo-oa-1:oa-msg-1"))
            self.assertIsNotNone(saved)
            self.assertEqual("Xin chào OA", saved.content)

    def test_invalid_oa_signature_is_rejected_before_persistence(self):
        payload = self.oa_text_payload("oa-msg-invalid")
        response = self.client.post(
            "/api/webhooks/zalo",
            headers={
                "X-ZEvent-Signature": "mac=" + ("0" * 64),
                "Content-Type": "application/json",
            },
            content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
        )

        self.assertEqual(401, response.status_code)

    def test_empty_webhook_probe_returns_200_without_authentication(self):
        response = self.client.post(
            "/api/webhooks/zalo",
            headers={"Content-Type": "application/json"},
            json={},
        )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual({"status": "received", "processed": 0}, response.json())

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
