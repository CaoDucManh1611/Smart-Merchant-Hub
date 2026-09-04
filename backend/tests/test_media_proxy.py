import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.media import router  # noqa: F401 - route contract import
from app.db.dependencies import get_db
from app.main import app
from app.models import Business, Channel, Conversation, Customer, Message, MessageAttachment
from app.services.media_resolver import build_media_url


class _Response:
    content = b"audio-bytes"
    headers = {"content-type": "audio/ogg"}

    def raise_for_status(self):
        return None


class MediaProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="One", slug="one")
            two = Business(name="Two", slug="two")
            db.add_all([one, two])
            db.flush()
            channel = Channel(
                business_id=one.id,
                channel_type="telegram",
                name="Telegram",
                external_account_id="bot-1",
            )
            customer = Customer(business_id=one.id, channel="telegram", external_user_id="u1")
            db.add_all([channel, customer])
            db.flush()
            conversation = Conversation(business_id=one.id, customer_id=customer.id, channel_id=channel.id, channel="telegram")
            db.add(conversation)
            db.flush()
            message = Message(conversation_id=conversation.id, channel="telegram", external_user_id="u1", external_message_id="m1", direction="inbound")
            db.add(message)
            db.flush()
            attachment = MessageAttachment(
                business_id=one.id,
                message_id=message.id,
                channel_id=channel.id,
                media_type="audio",
                source_url="https://cdn.example/audio.ogg",
            )
            db.add(attachment)
            db.commit()
            cls.attachment_id = attachment.id

            other_channel = Channel(business_id=two.id, channel_type="telegram", name="Other", external_account_id="bot-2")
            db.add(other_channel)
            db.flush()
            other_customer = Customer(business_id=two.id, channel="telegram", external_user_id="u2")
            db.add(other_customer)
            db.flush()
            other_conversation = Conversation(business_id=two.id, customer_id=other_customer.id, channel_id=other_channel.id, channel="telegram")
            db.add(other_conversation)
            db.flush()
            other_message = Message(conversation_id=other_conversation.id, channel="telegram", external_user_id="u2", external_message_id="m2", direction="inbound")
            db.add(other_message)
            db.flush()
            other_attachment = MessageAttachment(business_id=two.id, message_id=other_message.id, channel_id=other_channel.id, media_type="audio", source_url="https://cdn.example/other.ogg")
            db.add(other_attachment)
            db.commit()
            cls.other_attachment_id = other_attachment.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    @patch("app.services.media_resolver.httpx.get", return_value=_Response())
    def test_media_proxy_streams_attachment_for_current_tenant(self, get):
        response = self.client.get(f"/api/media/{self.attachment_id}", headers={"X-Business-Id": "1"})
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(b"audio-bytes", response.content)

    @patch("app.services.media_resolver.httpx.get", return_value=_Response())
    def test_media_proxy_accepts_signed_browser_url_without_custom_header(self, get):
        url = build_media_url(attachment_id=self.attachment_id, business_id=1)
        response = self.client.get(url)
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(b"audio-bytes", response.content)

    def test_media_proxy_rejects_tampered_signed_browser_url(self):
        url = build_media_url(attachment_id=self.attachment_id, business_id=1).replace(
            "business_id=1", "business_id=2"
        )
        response = self.client.get(url)
        self.assertEqual(401, response.status_code)

    def test_media_proxy_rejects_cross_tenant_attachment(self):
        response = self.client.get(f"/api/media/{self.other_attachment_id}", headers={"X-Business-Id": "1"})
        self.assertEqual(404, response.status_code)


if __name__ == "__main__":
    unittest.main()
