"""Provider webhook contracts for the tenant-scoped Unified Inbox."""

import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.dependencies import get_db
from app.main import app
from app.models import Business, Channel, ChannelEvent, Conversation, Customer, Message


class UnifiedInboxWebhookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Unified inbox", slug="unified-inbox")
            db.add(business)
            db.flush()
            db.add_all([
                Channel(business_id=business.id, channel_type="facebook", name="Facebook", external_account_id="fb-page", status="active"),
                Channel(business_id=business.id, channel_type="instagram", name="Instagram", external_account_id="ig-account", status="active"),
                Channel(
                    business_id=business.id,
                    channel_type="telegram",
                    name="Telegram",
                    external_account_id="tg-bot",
                    status="active",
                    config={"webhook_secret": "telegram-unified-secret"},
                ),
                Channel(
                    business_id=business.id,
                    channel_type="zalo",
                    name="Zalo",
                    external_account_id="zalo-bot",
                    status="active",
                    config={"webhook_secret": "zalo-unified-secret"},
                ),
            ])
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
    def _meta_request(path: str, payload: dict, app_secret: str):
        body = json.dumps(payload, separators=(",", ":")).encode()
        signature = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
        return path, body, {"Content-Type": "application/json", "X-Hub-Signature-256": f"sha256={signature}"}

    def test_all_core_channels_persist_to_the_same_tenant_unified_inbox(self):
        app_secret = "unified-inbox-meta-secret"
        facebook = {
            "object": "page",
            "entry": [{
                "id": "fb-page",
                "messaging": [{
                    "sender": {"id": "fb-user"},
                    "recipient": {"id": "fb-page"},
                    "timestamp": 1700000000000,
                    "message": {"mid": "fb-unified-1", "text": "Tin Facebook"},
                }],
            }],
        }
        instagram = {
            "object": "instagram",
            "entry": [{
                "id": "ig-account",
                "messaging": [{
                    "sender": {"id": "ig-user"},
                    "recipient": {"id": "ig-account"},
                    "timestamp": 1700000000001,
                    "message": {"mid": "ig-unified-1", "text": "Tin Instagram"},
                }],
            }],
        }
        telegram = {
            "update_id": 101,
            "message": {
                "message_id": 1,
                "date": 1700000002,
                "from": {"id": 3001, "first_name": "Telegram"},
                "chat": {"id": 3001},
                "text": "Tin Telegram",
            },
        }
        zalo = {
            "event_name": "message.text.received",
            "message": {
                "message_id": "zalo-unified-1",
                "date": 1700000003000,
                "chat": {"id": "zalo-user", "chat_type": "PRIVATE"},
                "from": {"id": "zalo-user", "display_name": "Zalo Buyer", "is_bot": False},
                "text": "Tin Zalo",
            },
        }
        fb_path, fb_body, fb_headers = self._meta_request("/api/webhooks/facebook", facebook, app_secret)
        ig_path, ig_body, ig_headers = self._meta_request("/api/webhooks/instagram", instagram, app_secret)

        with patch.object(settings, "ENVIRONMENT", "production"), patch.object(settings, "META_APP_SECRET", app_secret), patch(
            "app.services.customer_fact_extractor.process_customer_fact_extraction_background"
        ), patch(
            "app.services.auto_reply_service.process_rag_auto_reply_background"
        ):
            responses = [
                self.client.post(fb_path, content=fb_body, headers=fb_headers),
                self.client.post(ig_path, content=ig_body, headers=ig_headers),
                self.client.post(
                    "/api/webhooks/telegram",
                    json=telegram,
                    headers={"X-Telegram-Bot-Api-Secret-Token": "telegram-unified-secret"},
                ),
                self.client.post(
                    "/api/webhooks/zalo",
                    json=zalo,
                    headers={"X-Bot-Api-Secret-Token": "zalo-unified-secret"},
                ),
            ]

        self.assertTrue(all(response.status_code == 200 for response in responses), [response.text for response in responses])
        with Session(self.engine) as db:
            messages = db.scalars(select(Message).order_by(Message.id)).all()
            self.assertEqual(["facebook", "instagram", "telegram", "zalo"], [message.channel for message in messages])
            self.assertEqual(4, db.query(ChannelEvent).count())
            conversations = db.scalars(select(Conversation).order_by(Conversation.id)).all()
            self.assertEqual(4, len(conversations))
            self.assertTrue(all(conversation.business_id == self.business_id for conversation in conversations))
            customers = db.scalars(select(Customer).order_by(Customer.id)).all()
            self.assertTrue(all(customer.business_id == self.business_id for customer in customers))


if __name__ == "__main__":
    unittest.main()
