import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.channel import Channel
from app.models.conversation import Conversation
from app.models.customer import Customer


class InstagramOutboundApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Instagram Outbound", slug="instagram-outbound")
            db.add(business)
            db.flush()
            channel = Channel(
                business_id=business.id,
                channel_type="instagram",
                name="Shop Instagram",
                external_account_id="ig-account-1",
                status="active",
            )
            customer = Customer(
                business_id=business.id,
                channel="instagram",
                external_user_id="17841400000000001",
            )
            invalid_customer = Customer(
                business_id=business.id,
                channel="instagram",
                external_user_id="USER_111",
            )
            db.add_all([channel, customer, invalid_customer])
            db.flush()
            conversation = Conversation(
                business_id=business.id,
                customer_id=customer.id,
                channel_id=channel.id,
                channel="instagram",
            )
            invalid_conversation = Conversation(
                business_id=business.id,
                customer_id=invalid_customer.id,
                channel_id=channel.id,
                channel="instagram",
            )
            db.add_all([conversation, invalid_conversation])
            db.commit()
            cls.conversation_id = conversation.id
            cls.invalid_conversation_id = invalid_conversation.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_unified_instagram_send_receives_tenant_context(self):
        with patch("app.api.conversations.send_instagram_message") as send:
            send.return_value = {"message_id": "ig-message-1"}
            response = self.client.post(
                f"/api/conversations/{self.conversation_id}/send",
                headers={"X-Business-Id": "1"},
                data={"text": "Xin chào Instagram"},
            )

        self.assertEqual(200, response.status_code, response.text)
        kwargs = send.call_args.kwargs
        self.assertEqual("17841400000000001", kwargs["recipient_id"])
        self.assertEqual("Xin chào Instagram", kwargs["text"])
        self.assertEqual(1, kwargs["business_id"])
        self.assertIsNotNone(kwargs["db"])

    def test_placeholder_instagram_recipient_is_rejected_before_provider_call(self):
        with patch("app.services.instagram_service.send_instagram_request") as send:
            response = self.client.post(
                f"/api/conversations/{self.invalid_conversation_id}/send",
                headers={"X-Business-Id": "1"},
                data={"text": "Không gửi ID mẫu"},
            )

        self.assertEqual(422, response.status_code)
        self.assertIn("Scoped ID", response.json()["detail"])
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
