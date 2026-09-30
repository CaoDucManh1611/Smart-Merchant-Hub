import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.models import Business, Channel, Conversation, Customer
from app.services.channel_credentials import encrypt_token
from app.services.zalo_service import send_zalo_message


class ZaloOutboundServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        settings.CHANNEL_ENCRYPTION_KEY = "zalo-outbound-test-key"
        with Session(cls.engine) as db:
            business = Business(name="Zalo Outbound", slug="zalo-outbound")
            db.add(business)
            db.flush()
            channel = Channel(
                business_id=business.id,
                channel_type="zalo",
                name="Zalo Bot",
                external_account_id="zalo-bot-1",
                access_token_encrypted=encrypt_token("zalo-token", settings.CHANNEL_ENCRYPTION_KEY),
                status="active",
                config={"webhook_secret": "zalo-secret"},
            )
            customer = Customer(
                business_id=business.id,
                channel="zalo",
                external_user_id="z-user-1",
            )
            db.add_all([channel, customer])
            db.flush()
            conversation = Conversation(
                business_id=business.id,
                customer_id=customer.id,
                channel_id=channel.id,
                channel="zalo",
            )
            db.add(conversation)
            db.commit()
            cls.business_id = business.id
            cls.conversation_id = conversation.id

    def test_sends_using_conversation_channel_and_promotes_message_id(self):
        with Session(self.engine) as db, patch(
            "app.services.zalo_service.ZaloAdapter.send_message",
            return_value={"ok": True, "result": {"message_id": "z-out-1"}},
        ) as send:
            result = send_zalo_message(
                db=db,
                business_id=self.business_id,
                conversation_id=self.conversation_id,
                recipient_id="z-user-1",
                text="Xin chào từ CRM",
            )

        self.assertEqual("zalo:zalo-bot-1:z-out-1", result["message_id"])
        send.assert_called_once_with(
            recipient_external_id="z-user-1",
            text="Xin chào từ CRM",
            access_token="zalo-token",
        )


if __name__ == "__main__":
    unittest.main()
