import unittest
from unittest.mock import ANY, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models import Business, Channel, Conversation, Customer, Message


class UnifiedInboxActionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            primary = Business(name="Inbox primary", slug="inbox-primary")
            other = Business(name="Inbox other", slug="inbox-other")
            db.add_all([primary, other])
            db.flush()
            channel = Channel(
                business_id=primary.id,
                channel_type="zalo",
                name="Zalo inbox",
                external_account_id="zalo-inbox-1",
                status="active",
            )
            customer = Customer(
                business_id=primary.id,
                channel="zalo",
                external_user_id="zalo-customer-1",
                name="Zalo Buyer",
            )
            other_customer = Customer(
                business_id=other.id,
                channel="zalo",
                external_user_id="zalo-customer-2",
            )
            db.add_all([channel, customer, other_customer])
            db.flush()
            conversation = Conversation(
                business_id=primary.id,
                customer_id=customer.id,
                channel_id=channel.id,
                channel="zalo",
            )
            other_conversation = Conversation(
                business_id=other.id,
                customer_id=other_customer.id,
                channel="zalo",
            )
            db.add_all([conversation, other_conversation])
            db.flush()
            db.add_all([
                Message(
                    conversation_id=conversation.id,
                    channel="zalo",
                    external_user_id="zalo-customer-1",
                    external_message_id="zalo:inbox:inbound-1",
                    direction="inbound",
                    content="Tin chưa đọc 1",
                    status="received",
                ),
                Message(
                    conversation_id=conversation.id,
                    channel="zalo",
                    external_user_id="zalo-customer-1",
                    external_message_id="zalo:inbox:inbound-2",
                    direction="inbound",
                    content="Tin chưa đọc 2",
                    status="received",
                ),
                Message(
                    conversation_id=conversation.id,
                    channel="zalo",
                    external_user_id="zalo-customer-1",
                    external_message_id="zalo:inbox:outbound-1",
                    direction="outbound",
                    content="Tin nhân viên gửi",
                    status="sent",
                ),
            ])
            db.commit()
            cls.business_id = primary.id
            cls.other_business_id = other.id
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

    def headers(self, business_id=None):
        return {"X-Business-Id": str(business_id or self.business_id)}

    def test_mark_read_is_idempotent_and_never_crosses_tenants(self):
        listing = self.client.get("/api/conversations", headers=self.headers())
        self.assertEqual(200, listing.status_code, listing.text)
        row = next(item for item in listing.json()["items"] if item["conversation_id"] == self.conversation_id)
        self.assertEqual(2, row["unread_count"])
        self.assertEqual("auto", row["bot_mode"])

        marked = self.client.post(
            f"/api/conversations/{self.conversation_id}/mark-read",
            headers=self.headers(),
        )
        self.assertEqual(200, marked.status_code, marked.text)
        self.assertEqual(2, marked.json()["marked_count"])

        repeated = self.client.post(
            f"/api/conversations/{self.conversation_id}/mark-read",
            headers=self.headers(),
        )
        self.assertEqual(200, repeated.status_code, repeated.text)
        self.assertEqual(0, repeated.json()["marked_count"])

        with Session(self.engine) as db:
            rows = db.scalars(select(Message).where(Message.conversation_id == self.conversation_id)).all()
            inbound = [row for row in rows if row.direction == "inbound"]
            outbound = [row for row in rows if row.direction == "outbound"]
            self.assertEqual(["read", "read"], [row.status for row in inbound])
            self.assertEqual(["sent"], [row.status for row in outbound])

        cross_tenant = self.client.post(
            f"/api/conversations/{self.conversation_id}/mark-read",
            headers=self.headers(self.other_business_id),
        )
        self.assertEqual(404, cross_tenant.status_code)

    def test_conversation_listing_exposes_human_takeover_mode(self):
        with Session(self.engine) as db:
            db.get(Conversation, self.conversation_id).bot_mode = "human"
            db.commit()

        listing = self.client.get("/api/conversations", headers=self.headers())
        self.assertEqual(200, listing.status_code, listing.text)
        row = next(item for item in listing.json()["items"] if item["conversation_id"] == self.conversation_id)
        self.assertEqual("human", row["bot_mode"])

        with Session(self.engine) as db:
            db.get(Conversation, self.conversation_id).bot_mode = "auto"
            db.commit()

    def test_unified_send_dispatches_zalo_text_and_persists_outbound_message(self):
        with patch(
            "app.api.conversations.send_zalo_message",
            return_value={"ok": True, "message_id": "zalo:zalo-inbox-1:outbound-2"},
        ) as send:
            response = self.client.post(
                f"/api/conversations/{self.conversation_id}/send",
                headers=self.headers(),
                data={"text": "Phản hồi qua Zalo"},
            )

        self.assertEqual(200, response.status_code, response.text)
        send.assert_called_once_with(
            db=ANY,
            business_id=self.business_id,
            conversation_id=self.conversation_id,
            recipient_id="zalo-customer-1",
            text="Phản hồi qua Zalo",
        )
        with Session(self.engine) as db:
            saved = db.scalar(select(Message).where(Message.external_message_id == "zalo:zalo-inbox-1:outbound-2"))
            self.assertIsNotNone(saved)
            self.assertEqual("outbound", saved.direction)
            self.assertEqual("Phản hồi qua Zalo", saved.content)


if __name__ == "__main__":
    unittest.main()
