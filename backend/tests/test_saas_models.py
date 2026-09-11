import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.business import Business, ServicePlan, Subscription, User
from app.models.saas import (
    DataLifecycleRequest,
    PlatformMembership,
    SaaSUsage,
    TenantSchemaRegistry,
)


class SaaSModelTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(self.engine)

    def test_control_plane_records_are_tenant_scoped_and_usage_is_unique_per_period(self):
        with Session(self.engine) as db:
            one = Business(name="Shop One", slug="shop-one")
            two = Business(name="Shop Two", slug="shop-two")
            db.add_all([one, two])
            db.flush()
            plan = ServicePlan(
                code="secure",
                name="Secure",
                max_users=3,
                max_channels=2,
                max_documents=5,
                max_rag_chunks=50,
                max_ai_calls=100,
                max_ai_cost=25,
            )
            db.add(plan)
            db.flush()
            db.add_all([
                Subscription(business_id=one.id, plan_id=plan.id, status="active"),
                Subscription(business_id=two.id, plan_id=plan.id, status="active"),
            ])
            user = User(business_id=one.id, full_name="Platform", email="platform@test", role="owner")
            db.add(user)
            db.flush()
            db.add_all([
                PlatformMembership(user_id=user.id),
                SaaSUsage(business_id=one.id, resource="staff_users", period_start=datetime(2026, 9, 1), used=2),
                SaaSUsage(business_id=two.id, resource="staff_users", period_start=datetime(2026, 9, 1), used=1),
                DataLifecycleRequest(business_id=one.id, request_key="export-1", kind="export", status="queued"),
                DataLifecycleRequest(business_id=two.id, request_key="export-1", kind="export", status="queued"),
                TenantSchemaRegistry(business_id=one.id, schema_name="tenant_1", state="proposed"),
                TenantSchemaRegistry(business_id=two.id, schema_name="tenant_2", state="proposed"),
            ])
            db.commit()

            self.assertEqual(50, plan.max_rag_chunks)
            self.assertEqual(100, plan.max_ai_calls)
            self.assertEqual(25, plan.max_ai_cost)
            self.assertEqual(2, db.query(SaaSUsage).count())
            self.assertEqual(2, db.query(DataLifecycleRequest).count())

            duplicate = SaaSUsage(
                business_id=one.id,
                resource="staff_users",
                period_start=datetime(2026, 9, 1),
                used=1,
            )
            db.add(duplicate)
            with self.assertRaises(IntegrityError):
                db.commit()


if __name__ == "__main__":
    unittest.main()
