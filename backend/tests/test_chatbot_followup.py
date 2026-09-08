import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.business import Business
from app.models.chatbot_followup import ChatbotFollowUp
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.services.chatbot_followup import dispatch_due_followups, schedule_followup


class ChatbotFollowUpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Followup shop", slug="followup-shop")
            db.add(business)
            db.flush()
            customer = Customer(business_id=business.id, channel="telegram", external_user_id="followup-customer", name="Mai")
            db.add(customer)
            db.flush()
            conversation = Conversation(business_id=business.id, customer_id=customer.id, channel="telegram")
            db.add(conversation)
            db.commit()
            cls.business_id, cls.conversation_id, cls.customer_id = business.id, conversation.id, customer.id

    def test_schedule_and_dispatch_is_idempotent(self):
        with Session(self.engine) as db:
            row = schedule_followup(db, self.business_id, self.conversation_id, "Nhắc khách xác nhận đơn", datetime.utcnow() - timedelta(minutes=1), kind="cart_abandoned")
            db.commit()
            self.assertEqual("scheduled", row.status)
            with patch("app.services.chatbot_followup._send_followup", return_value={"message_id": "followup-1"}) as send:
                result = dispatch_due_followups(db, self.business_id, limit=10)
                self.assertEqual(1, result["sent"])
                self.assertEqual(1, send.call_count)
                result_again = dispatch_due_followups(db, self.business_id, limit=10)
                self.assertEqual(0, result_again["sent"])
