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
from app.models.customer_collection import CustomerConsent
from app.services.chatbot_followup import (
    dispatch_due_followups,
    schedule_abandoned_checkout_followup,
    schedule_post_delivery_followup,
    schedule_followup,
    schedule_inactive_customer_followups,
    schedule_segment_followups,
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
            db.add(CustomerConsent(
                business_id=self.business_id, customer_id=self.customer_id,
                purpose="marketing", status="granted",
            ))
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

    def test_winback_requires_consent_and_revocation_blocks_due_send(self):
        current = datetime.now(timezone.utc).replace(tzinfo=None)
        with Session(self.engine) as db:
            customer = Customer(
                business_id=self.business_id, channel="telegram",
                external_user_id="followup-consent-fixture",
            )
            db.add(customer)
            db.flush()
            conversation = Conversation(
                business_id=self.business_id, customer_id=customer.id, channel="telegram",
            )
            db.add(conversation)
            db.flush()
            with self.assertRaisesRegex(ValueError, "followup_consent_required"):
                schedule_followup(
                    db, self.business_id, conversation.id, "Winback",
                    current - timedelta(minutes=1), kind="customer_winback",
                )
            db.add(CustomerConsent(
                business_id=self.business_id, customer_id=customer.id,
                purpose="marketing", status="granted",
            ))
            db.flush()
            row = schedule_followup(
                db, self.business_id, conversation.id, "Winback",
                current - timedelta(minutes=1), kind="customer_winback",
            )
            db.add(CustomerConsent(
                business_id=self.business_id, customer_id=customer.id,
                purpose="marketing", status="revoked",
            ))
            db.commit()
            with patch("app.services.auto_reply_service._send_channel_reply") as send:
                result = dispatch_due_followups(
                    db, self.business_id, now=current, followup_id=row.id,
                )
            self.assertEqual(0, result["sent"])
            self.assertEqual(1, result["skipped"])
            self.assertEqual("cancelled", row.status)
            send.assert_not_called()

    def test_followup_frequency_cap_defers_next_customer_message(self):
        current = datetime.now(timezone.utc).replace(tzinfo=None)
        with Session(self.engine) as db:
            customer = Customer(
                business_id=self.business_id, channel="telegram",
                external_user_id="followup-frequency-fixture",
            )
            db.add(customer)
            db.flush()
            conversation = Conversation(
                business_id=self.business_id, customer_id=customer.id, channel="telegram",
            )
            db.add(conversation)
            db.flush()
            first = schedule_followup(
                db, self.business_id, conversation.id, "First",
                current - timedelta(minutes=1), kind="post_delivery",
            )
            db.commit()
            with patch("app.services.chatbot_followup._send_followup"):
                self.assertEqual(
                    1, dispatch_due_followups(db, self.business_id, now=current, followup_id=first.id)["sent"],
                )
            second = schedule_followup(
                db, self.business_id, conversation.id, "Second",
                current, kind="post_delivery",
            )
            self.assertGreaterEqual(second.run_at, current + timedelta(hours=24))

    def test_ambiguous_provider_failure_never_resends_followup(self):
        current = datetime.now(timezone.utc).replace(tzinfo=None)
        with Session(self.engine) as db:
            customer = Customer(
                business_id=self.business_id, channel="telegram",
                external_user_id="followup-ambiguous-fixture",
            )
            db.add(customer)
            db.flush()
            conversation = Conversation(
                business_id=self.business_id, customer_id=customer.id, channel="telegram",
            )
            db.add(conversation)
            db.flush()
            row = schedule_followup(
                db, self.business_id, conversation.id, "Care message",
                current - timedelta(minutes=1), kind="post_delivery",
            )
            db.commit()
            with patch(
                "app.services.auto_reply_service._get_conversation_recipient",
                return_value=("telegram", "fixture-customer"),
            ), patch(
                "app.services.auto_reply_service._send_channel_reply",
                side_effect=TimeoutError("provider response was lost"),
            ) as send:
                first = dispatch_due_followups(db, self.business_id, now=current, followup_id=row.id)
                again = dispatch_due_followups(db, self.business_id, now=current, followup_id=row.id)
            db.refresh(row)
            self.assertEqual("delivery_unknown", row.status)
            self.assertEqual(0, first["sent"])
            self.assertEqual(0, again["sent"])
            send.assert_called_once()

    def test_stale_sending_followup_requires_reconciliation_not_resend(self):
        current = datetime.now(timezone.utc).replace(tzinfo=None)
        with Session(self.engine) as db:
            customer = Customer(
                business_id=self.business_id, channel="telegram",
                external_user_id="followup-stale-fixture",
            )
            db.add(customer)
            db.flush()
            conversation = Conversation(
                business_id=self.business_id, customer_id=customer.id, channel="telegram",
            )
            db.add(conversation)
            db.flush()
            row = ChatbotFollowUp(
                business_id=self.business_id, customer_id=customer.id,
                conversation_id=conversation.id, kind="post_delivery",
                message="Care message", status="sending",
                run_at=current - timedelta(minutes=10),
                idempotency_key="stale-followup-fixture",
            )
            db.add(row)
            db.commit()
            with patch("app.services.chatbot_followup._send_followup") as send:
                result = dispatch_due_followups(db, self.business_id, now=current, followup_id=row.id)
            db.refresh(row)
            self.assertEqual(0, result["sent"])
            self.assertEqual("delivery_unknown", row.status)
            send.assert_not_called()

    def test_segment_followups_are_consent_aware_tenant_scoped_and_idempotent(self):
        current = datetime.now(timezone.utc).replace(tzinfo=None)
        with Session(self.engine) as db:
            allowed = Customer(
                business_id=self.business_id, channel="telegram",
                external_user_id="segment-allowed",
            )
            blocked = Customer(
                business_id=self.business_id, channel="telegram",
                external_user_id="segment-blocked",
            )
            other_business = Business(name="Other followup shop", slug="other-followup-shop")
            db.add_all([allowed, blocked, other_business])
            db.flush()
            other_customer = Customer(
                business_id=other_business.id, channel="telegram",
                external_user_id="segment-other-tenant",
            )
            db.add(other_customer)
            db.flush()
            db.add_all([
                Conversation(business_id=self.business_id, customer_id=allowed.id, channel="telegram"),
                Conversation(business_id=self.business_id, customer_id=blocked.id, channel="telegram"),
                Conversation(business_id=other_business.id, customer_id=other_customer.id, channel="telegram"),
                CustomerConsent(
                    business_id=self.business_id, customer_id=allowed.id,
                    purpose="marketing", status="granted",
                ),
            ])
            db.commit()

            first = schedule_segment_followups(
                db,
                business_id=self.business_id,
                segment_id=91,
                customer_ids=[allowed.id, blocked.id, other_customer.id],
                message="Ưu đãi dành cho nhóm VIP",
                run_at=current + timedelta(hours=1),
            )
            db.commit()
            second = schedule_segment_followups(
                db,
                business_id=self.business_id,
                segment_id=91,
                customer_ids=[allowed.id, blocked.id, other_customer.id],
                message="Ưu đãi dành cho nhóm VIP",
                run_at=current + timedelta(hours=1),
            )
            db.commit()

            rows = db.query(ChatbotFollowUp).filter(
                ChatbotFollowUp.business_id == self.business_id,
                ChatbotFollowUp.kind == "segment_campaign",
            ).all()
            self.assertEqual(1, first["scheduled"])
            self.assertEqual(1, first["consent_required"])
            self.assertEqual(1, first["not_found"])
            self.assertEqual(first["followup_ids"], second["followup_ids"])
            self.assertEqual(1, len(rows))
            self.assertEqual(91, rows[0].metadata_["segment_id"])
