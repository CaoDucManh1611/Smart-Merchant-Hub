import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.onboarding import purchase_subscription, subscription_summary
from app.api.platform import approve_subscription_request
from app.database.bootstrap import ensure_default_plans
from app.models.audit_log import AuditLog
from app.models.business import Business, ServicePlan, Subscription, User
from app.models.channel import Channel
from app.schemas.onboarding import OnboardingSubscriptionPurchase


class SubscriptionUpgradeFlowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Business.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            business = Business(name="Upgrade shop", slug="upgrade-shop")
            db.add(business)
            db.flush()
            owner = User(business_id=business.id, full_name="Shop Owner", email="owner@example.test", role="owner")
            db.add(owner)
            ensure_default_plans(db)
            starter = db.query(ServicePlan).filter(ServicePlan.code == "starter").one()
            db.add(Subscription(business_id=business.id, plan_id=starter.id, status="active"))
            db.commit()
            self.business_id = business.id
            self.owner_id = owner.id

    def tearDown(self):
        self.engine.dispose()

    def test_upgrade_keeps_current_plan_until_approval_then_replaces_it(self):
        with Session(self.engine) as db:
            owner = db.get(User, self.owner_id)
            request = purchase_subscription(
                self.business_id,
                OnboardingSubscriptionPurchase(
                    plan_code="scale",
                    contact_name="Shop Owner",
                    contact_email="owner@example.test",
                    shop_name="Upgrade shop",
                ),
                db,
                owner,
            )
            self.assertEqual("pending", request["status"])
            self.assertEqual("Scale", request["plan_name"])

            active_before = db.query(Subscription).filter(Subscription.business_id == self.business_id, Subscription.status == "active").one()
            self.assertEqual("starter", active_before.plan.code)
            summary = subscription_summary(self.business_id, db, owner)
            self.assertEqual("pending", summary["subscription"]["status"])
            self.assertEqual("scale", summary["subscription"]["plan_code"])

            approved = approve_subscription_request(request["id"], db, owner)
            self.assertEqual("active", approved["status"])
            active_after = db.query(Subscription).filter(Subscription.business_id == self.business_id, Subscription.status == "active").one()
            self.assertEqual("scale", active_after.plan.code)
            self.assertEqual(1, db.query(Subscription).filter(Subscription.business_id == self.business_id, Subscription.status == "cancelled").count())
