import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.business import Business
from app.models.chatbot_followup import ChatbotFollowUp
from app.models.sales import Order
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.services.chatbot_followup import (
    dispatch_due_followups,
    schedule_abandoned_checkout_followup,
    schedule_post_delivery_followup,
    schedule_followup,
    schedule_inactive_customer_followups,
)


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
            row = schedule_followup(
                db,
                self.business_id,
                self.conversation_id,
                "Nhắc khách xác nhận đơn",
                datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=1),
                kind="cart_abandoned",
            )
            db.commit()
            self.assertEqual("scheduled", row.status)
            with patch("app.services.chatbot_followup._send_followup", return_value={"message_id": "followup-1"}) as send:
                result = dispatch_due_followups(db, self.business_id, limit=10)
                self.assertEqual(1, result["sent"])
                self.assertEqual(1, send.call_count)
                result_again = dispatch_due_followups(db, self.business_id, limit=10)
                self.assertEqual(0, result_again["sent"])

    def test_special_followups_are_idempotent_by_business_event(self):
        with Session(self.engine) as db:
            abandoned = schedule_abandoned_checkout_followup(
                db,
                business_id=self.business_id,
                conversation_id=self.conversation_id,
                session_id=41,
                run_at=datetime.now(timezone.utc) + timedelta(hours=2),
            )
            abandoned_again = schedule_abandoned_checkout_followup(
                db,
                business_id=self.business_id,
                conversation_id=self.conversation_id,
                session_id=41,
                run_at=datetime.now(timezone.utc) + timedelta(hours=3),
            )
            delivered = schedule_post_delivery_followup(
                db,
                business_id=self.business_id,
                conversation_id=self.conversation_id,
                order_id=99,
                run_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
            delivered_again = schedule_post_delivery_followup(
                db,
                business_id=self.business_id,
                conversation_id=self.conversation_id,
                order_id=99,
                run_at=datetime.now(timezone.utc) + timedelta(hours=48),
            )
            self.assertEqual(abandoned.id, abandoned_again.id)
            self.assertEqual(delivered.id, delivered_again.id)
            self.assertEqual("cart_abandoned", abandoned.kind)
            self.assertEqual("post_delivery", delivered.kind)

    def test_inactive_prior_buyer_gets_one_monthly_winback(self):
        current = datetime.now(timezone.utc).replace(tzinfo=None)
        with Session(self.engine) as db:
            db.add(Order(
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=self.conversation_id,
                order_number="WINBACK-OLD-1",
                status="completed",
                total_amount=100,
                created_at=current - timedelta(days=90),
                updated_at=current - timedelta(days=90),
            ))
            db.commit()
            first = schedule_inactive_customer_followups(
                db,
                business_id=self.business_id,
                inactive_days=30,
                now=current,
                run_at=current + timedelta(minutes=5),
            )
            db.commit()
            second = schedule_inactive_customer_followups(
                db,
                business_id=self.business_id,
                inactive_days=30,
                now=current,
                run_at=current + timedelta(minutes=10),
            )
            self.assertEqual(1, first["scheduled"])
            self.assertEqual(0, second["scheduled"])
            self.assertEqual(1, db.query(ChatbotFollowUp).filter(ChatbotFollowUp.kind == "customer_winback").count())
