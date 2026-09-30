import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.business import Business
from app.models.chatbot_followup import ChatbotFollowUp
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.crm_job import CrmJob
from app.models.customer_feedback import CustomerFeedback
from app.services.csat_service import (
    record_csat_response,
    schedule_csat_survey,
    summarize_csat,
)


class CsatServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="CSAT Shop", slug="csat-shop")
            db.add(business)
            db.flush()
            customer = Customer(
                business_id=business.id,
                channel="telegram",
                external_user_id="csat-user",
                name="CSAT Customer",
            )
            db.add(customer)
            db.flush()
            conversation = Conversation(
                business_id=business.id,
                customer_id=customer.id,
                channel="telegram",
            )
            db.add(conversation)
            db.commit()
            cls.business_id = business.id
            cls.customer_id = customer.id
            cls.conversation_id = conversation.id

    def test_schedule_is_idempotent_and_creates_a_followup(self):
        with Session(self.engine) as db:
            self._clear_feedback(db)
            run_at = datetime.now(timezone.utc) + timedelta(minutes=1)
            first = schedule_csat_survey(
                db,
                business_id=self.business_id,
                conversation_id=self.conversation_id,
                ticket_id=91,
                run_at=run_at,
            )
            second = schedule_csat_survey(
                db,
                business_id=self.business_id,
                conversation_id=self.conversation_id,
                ticket_id=91,
                run_at=run_at,
            )
            self.assertEqual(first.id, second.id)
            self.assertEqual("scheduled", first.status)
            self.assertEqual(1, db.query(CustomerFeedback).count())
            followup = db.query(ChatbotFollowUp).one()
            self.assertEqual(first.id, followup.metadata_["feedback_id"])
            self.assertEqual("csat", followup.kind)
            self.assertEqual(1, db.query(CrmJob).count())

    def test_rating_response_is_saved_once_and_summary_is_computed(self):
        with Session(self.engine) as db:
            self._clear_feedback(db)
            schedule_csat_survey(
                db,
                business_id=self.business_id,
                conversation_id=self.conversation_id,
                ticket_id=92,
                run_at=datetime.now(timezone.utc) + timedelta(minutes=1),
            )
            feedback = db.query(CustomerFeedback).one()
            self.assertFalse(record_csat_response(
                db,
                business_id=self.business_id,
                conversation_id=self.conversation_id,
                rating=5,
            ))
            feedback.status = "sent"
            db.commit()

            first = record_csat_response(
                db,
                business_id=self.business_id,
                conversation_id=self.conversation_id,
                rating=5,
                comment="Rất ổn",
            )
            duplicate = record_csat_response(
                db,
                business_id=self.business_id,
                conversation_id=self.conversation_id,
                rating=2,
                comment="trùng",
            )
            self.assertTrue(first)
            self.assertFalse(duplicate)
            self.assertEqual(5, feedback.rating)
            self.assertEqual("Rất ổn", feedback.comment)
            summary = summarize_csat(db, self.business_id)
            self.assertEqual(1, summary["responses"])
            self.assertEqual(5.0, summary["average_rating"])
            self.assertEqual(1.0, summary["satisfaction_rate"])

    @staticmethod
    def _clear_feedback(db):
        db.query(CrmJob).delete()
        db.query(ChatbotFollowUp).delete()
        db.query(CustomerFeedback).delete()
        db.commit()


if __name__ == "__main__":
    unittest.main()
