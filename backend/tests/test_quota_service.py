import unittest
from datetime import datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.business import Business, ServicePlan, Subscription
from app.models.saas import SaaSUsage
from app.services.quota_service import (
    QuotaExceededError,
    check_quota,
    release_quota,
    reserve_quota,
)


class QuotaServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            self.business = Business(name="Quota Shop", slug="quota-shop")
            db.add(self.business)
            db.flush()
            plan = ServicePlan(
                code="quota-plan",
                name="Quota plan",
                max_users=1,
                max_channels=1,
                max_documents=1,
                max_rag_chunks=2,
                max_ai_calls=2,
                max_ai_cost=Decimal("10.00"),
            )
            db.add(plan)
            db.flush()
            db.add(Subscription(business_id=self.business.id, plan_id=plan.id, status="active"))
            db.commit()
            self.business_id = self.business.id

    def test_reservation_rejects_limit_and_replay_is_idempotent(self):
        with Session(self.engine) as db:
            first = reserve_quota(
                db,
                self.business_id,
                "ai_calls",
                requested=2,
                idempotency_key="chat-1",
            )
            self.assertTrue(first.allowed)
            replay = reserve_quota(
                db,
                self.business_id,
                "ai_calls",
                requested=2,
                idempotency_key="chat-1",
            )
            self.assertEqual(first.used, replay.used)
            self.assertEqual(Decimal("2"), replay.used)
            with self.assertRaises(QuotaExceededError) as raised:
                reserve_quota(db, self.business_id, "ai_calls", requested=1, idempotency_key="chat-2")
            self.assertEqual("ai_calls", raised.exception.resource)
            self.assertEqual(2, raised.exception.limit)
            self.assertEqual(2, raised.exception.used)

    def test_check_quota_does_not_mutate_usage_and_missing_subscription_is_unlimited_in_development(self):
        with Session(self.engine) as db:
            decision = check_quota(db, self.business_id, "documents", requested=1)
            self.assertTrue(decision.allowed)
            self.assertEqual(0, db.query(SaaSUsage).count())

            legacy = Business(name="Legacy Shop", slug="legacy-shop")
            db.add(legacy)
            db.commit()
            decision = check_quota(db, legacy.id, "ai_calls", requested=999)
            self.assertTrue(decision.allowed)
            self.assertIsNone(decision.limit)

    def test_release_quota_frees_capacity_for_deleted_resources(self):
        with Session(self.engine) as db:
            reserve_quota(db, self.business_id, "documents", idempotency_key="doc-1")
            release_quota(db, self.business_id, "documents")
            decision = check_quota(db, self.business_id, "documents")
            self.assertTrue(decision.allowed)
            self.assertEqual(Decimal("0"), decision.used)


if __name__ == "__main__":
    unittest.main()
