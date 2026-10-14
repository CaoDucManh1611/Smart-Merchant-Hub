import unittest
from fastapi import HTTPException

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.onboarding import get_shop_subscription_summary, purchase_shop_plan
from app.database.bootstrap import ensure_default_plans
from app.models.audit_log import AuditLog
from app.models.business import Business, Payment, ServicePlan, Subscription, User
from app.models.channel import Channel
from app.schemas.onboarding import OnboardingPlanPurchase


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

    def test_downgrade_to_demo_is_rejected_and_keeps_active_access(self):
        with Session(self.engine) as db:
            owner = db.get(User, self.owner_id)
            with self.assertRaises(HTTPException) as error:
                purchase_shop_plan(self.business_id, OnboardingPlanPurchase(plan_code="demo"), db, db, owner)
            self.assertEqual(409, error.exception.status_code)
            self.assertEqual("starter", db.query(Subscription).filter_by(status="active").one().plan.code)
            self.assertEqual(0, db.query(Subscription).filter_by(status="pending").count())
            self.assertEqual(0, db.query(Payment).count())

    def test_chatbot_downgrade_is_rejected(self):
        with Session(self.engine) as db:
            owner = db.get(User, self.owner_id)
            starter = db.query(ServicePlan).filter(ServicePlan.code == "starter").one()
            db.add(Subscription(business_id=self.business_id, plan_id=starter.id, service_type="chatbot", status="active"))
            db.commit()

            with self.assertRaises(HTTPException) as error:
                purchase_shop_plan(
                    self.business_id,
                    OnboardingPlanPurchase(plan_code="demo", service_type="chatbot"),
                    db,
                    db,
                    owner,
                )

            self.assertEqual(409, error.exception.status_code)
            self.assertEqual(0, db.query(Subscription).filter_by(service_type="chatbot", status="pending").count())

    def test_package_request_does_not_cancel_pending_chatbot(self):
        with Session(self.engine) as db:
            owner = db.get(User, self.owner_id)
            chatbot = purchase_shop_plan(self.business_id, OnboardingPlanPurchase(plan_code="growth", service_type="chatbot"), db, db, owner)
            package = purchase_shop_plan(self.business_id, OnboardingPlanPurchase(plan_code="growth"), db, db, owner)
            self.assertNotEqual(chatbot.id, package.id)
            self.assertEqual("awaiting_payment", db.get(Subscription, chatbot.id).status)

    def test_price_change_replaces_unpaid_request_and_preserves_old_quote(self):
        with Session(self.engine) as db:
            owner = db.get(User, self.owner_id)
            request = purchase_shop_plan(self.business_id, OnboardingPlanPurchase(plan_code="growth"), db, db, owner)
            plan = db.query(ServicePlan).filter_by(code="growth").one()
            original = plan.price
            plan.price = original + 1000
            db.commit()
            repeated = purchase_shop_plan(self.business_id, OnboardingPlanPurchase(plan_code="growth"), db, db, owner)
            self.assertNotEqual(request.id, repeated.id)
            self.assertEqual(original + 1000, repeated.quoted_amount)
            self.assertEqual(original, db.get(Subscription, request.id).quoted_amount)
            self.assertEqual("cancelled", db.get(Subscription, request.id).status)
            fresh = purchase_shop_plan(self.business_id, OnboardingPlanPurchase(plan_code="growth"), db, db, owner)
            self.assertEqual(repeated.id, fresh.id)
            self.assertEqual(original + 1000, fresh.quoted_amount)

    def test_price_change_never_replaces_request_with_received_money(self):
        with Session(self.engine) as db:
            owner = db.get(User, self.owner_id)
            request = purchase_shop_plan(self.business_id, OnboardingPlanPurchase(plan_code="growth"), db, db, owner)
            db.add(Payment(business_id=self.business_id, subscription_id=request.id, amount=request.quoted_amount,
                           currency="VND", provider="manual", provider_transaction_id="PRICE-TEST", status="paid"))
            plan = db.query(ServicePlan).filter_by(code="growth").one()
            plan.price += 1000
            db.commit()
            with self.assertRaises(HTTPException) as error:
                purchase_shop_plan(self.business_id, OnboardingPlanPurchase(plan_code="growth"), db, db, owner)
            self.assertEqual(409, error.exception.status_code)
            self.assertEqual("awaiting_payment", db.get(Subscription, request.id).status)

    def test_upgrade_keeps_current_plan_until_approval_then_replaces_it(self):
        with Session(self.engine) as db:
            owner = db.get(User, self.owner_id)
            request = purchase_shop_plan(
                self.business_id,
                OnboardingPlanPurchase(
                    plan_code="growth",
                    contact_name="Shop Owner",
                    contact_email="owner@example.test",
                    shop_name="Upgrade shop",
                ),
                db,
                db,
                owner,
            )
            self.assertEqual("awaiting_payment", request.status)
            self.assertEqual("Gói VIP", request.plan_name)

            active_before = db.query(Subscription).filter(Subscription.business_id == self.business_id, Subscription.status == "active").one()
            self.assertEqual("starter", active_before.plan.code)
            summary = get_shop_subscription_summary(self.business_id, db, owner)
            self.assertEqual("awaiting_payment", summary.subscription.status)
            self.assertEqual("growth", summary.subscription.plan_code)

    def test_subscription_summary_reports_active_chatbot_plan_while_an_upgrade_is_pending(self):
        with Session(self.engine) as db:
            owner = db.get(User, self.owner_id)
            starter = db.query(ServicePlan).filter(ServicePlan.code == "starter").one()
            growth = db.query(ServicePlan).filter(ServicePlan.code == "growth").one()
            db.add(Subscription(
                business_id=self.business_id,
                plan_id=starter.id,
                service_type="chatbot",
                status="active",
            ))
            db.flush()
            db.add(Subscription(
                business_id=self.business_id,
                plan_id=growth.id,
                service_type="chatbot",
                status="pending",
            ))
            db.commit()

            summary = get_shop_subscription_summary(self.business_id, db, owner)

            self.assertEqual("active", summary.chatbot_subscription.status)
            self.assertEqual("starter", summary.chatbot_subscription.plan_code)
