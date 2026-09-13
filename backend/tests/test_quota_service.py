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
    quota_snapshot,
)
from app.services.channel_service import upsert_channel_connection


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

    def test_idempotency_key_cannot_be_reused_for_another_amount_or_resource(self):
        with Session(self.engine) as db:
            reserve_quota(db, self.business_id, "ai_calls", 1, idempotency_key="shared-key")
            with self.assertRaises(ValueError):
                reserve_quota(db, self.business_id, "ai_calls", 2, idempotency_key="shared-key")
            with self.assertRaises(ValueError):
                reserve_quota(db, self.business_id, "ai_cost", 1, idempotency_key="shared-key")

    def test_snapshot_warns_at_threshold_and_marks_only_true_overage_as_exceeded(self):
        with Session(self.engine) as db:
            reserve_quota(db, self.business_id, "ai_calls", 2, idempotency_key="near-limit")
            snapshot = quota_snapshot(db, self.business_id, warning_percent=0.8)
            self.assertTrue(snapshot["resources"]["ai_calls"]["near_limit"])
            self.assertFalse(snapshot["resources"]["ai_calls"]["exceeded"])

    def test_disconnected_channel_can_reactivate_without_losing_capacity_accounting(self):
        with Session(self.engine) as db:
            channel = upsert_channel_connection(
                db,
                business_id=self.business_id,
                channel_type="telegram",
                external_account_id="quota-reactivate-bot",
                name="Quota bot",
                access_token="secret",
                encryption_key="quota-test-encryption-key",
            )
            channel.status = "inactive"
            release_quota(db, self.business_id, "connected_channels")
            db.commit()
            reactivated = upsert_channel_connection(
                db,
                business_id=self.business_id,
                channel_type="telegram",
                external_account_id="quota-reactivate-bot",
                name="Quota bot",
                access_token="new-secret",
                encryption_key="quota-test-encryption-key",
            )
            self.assertEqual(channel.id, reactivated.id)
            self.assertEqual(Decimal("1"), check_quota(db, self.business_id, "connected_channels").used)
            with self.assertRaises(QuotaExceededError):
                upsert_channel_connection(
                    db,
                    business_id=self.business_id,
                    channel_type="zalo",
                    external_account_id="quota-second-channel",
                    name="Second",
                    access_token="secret",
                    encryption_key="quota-test-encryption-key",
                )


if __name__ == "__main__":
    unittest.main()
