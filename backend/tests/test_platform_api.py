import unittest
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.passwords import hash_password
from app.database.platform_session import get_platform_db
from app.db.dependencies import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.business import Business, ServicePlan, Subscription, User
from app.models.platform_control import PlatformProviderIncident
from app.models.saas import PlatformMembership


class PlatformApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            shop = Business(name="Platform Shop", slug="platform-shop")
            other = Business(name="Other Shop", slug="other-platform-shop")
            db.add_all([shop, other])
            db.flush()
            platform = User(
                business_id=shop.id,
                full_name="Platform Admin",
                email="platform-admin@test",
                role="owner",
                password_hash=hash_password("platform-password"),
            )
            agent = User(
                business_id=shop.id,
                full_name="Shop Agent",
                email="platform-agent@test",
                role="agent",
                password_hash=hash_password("agent-password"),
            )
            db.add_all([platform, agent])
            db.flush()
            db.add(PlatformMembership(user_id=platform.id))
            db.commit()
            cls.business_id = shop.id
            cls.other_business_id = other.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_platform_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def login(self, email, password):
        response = self.client.post(
            "/api/auth/login",
            headers={"X-Business-Id": str(self.business_id)},
            json={"email": email, "password": password},
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()["access_token"]

    def test_platform_member_lists_and_suspends_shop_with_audit(self):
        token = self.login("platform-admin@test", "platform-password")
        headers = {"Authorization": f"Bearer {token}", "X-Business-Id": str(self.other_business_id)}
        listed = self.client.get("/api/platform/shops", headers=headers)
        self.assertEqual(200, listed.status_code, listed.text)
        self.assertIn(self.business_id, [item["id"] for item in listed.json()["items"]])

        changed = self.client.patch(
            f"/api/platform/shops/{self.other_business_id}/status",
            headers=headers,
            json={"status": "suspended"},
        )
        self.assertEqual(200, changed.status_code, changed.text)
        self.assertEqual("suspended", changed.json()["status"])
        blocked = self.client.post(
            "/api/team",
            headers={"X-Business-Id": str(self.other_business_id)},
            json={"full_name": "Blocked", "email": "blocked@test", "role": "agent"},
        )
        self.assertEqual(423, blocked.status_code, blocked.text)
        with Session(self.engine) as db:
            audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.business_id == self.other_business_id,
                    AuditLog.resource_type == "business",
                    AuditLog.action == "platform_status_changed",
                )
            )
            self.assertIsNotNone(audit)

    def test_shop_agent_cannot_access_platform_endpoints(self):
        token = self.login("platform-agent@test", "agent-password")
        response = self.client.get(
            "/api/platform/shops",
            headers={"Authorization": f"Bearer {token}", "X-Business-Id": str(self.business_id)},
        )
        self.assertEqual(403, response.status_code)

    def test_platform_admin_can_register_and_stage_tenant_schema(self):
        token = self.login("platform-admin@test", "platform-password")
        headers = {"Authorization": f"Bearer {token}"}
        created = self.client.post(
            f"/api/platform/tenant-schemas/{self.business_id}",
            headers=headers,
        )
        self.assertEqual(200, created.status_code, created.text)
        self.assertEqual(f"tenant_{self.business_id}", created.json()["schema_name"])
        self.assertEqual("proposed", created.json()["state"])
        self.assertFalse(created.json()["feature_enabled"])

        repeated = self.client.post(
            f"/api/platform/tenant-schemas/{self.business_id}",
            headers=headers,
        )
        self.assertEqual(created.json()["id"], repeated.json()["id"])

        staged = self.client.patch(
            f"/api/platform/tenant-schemas/{self.business_id}",
            headers=headers,
            json={"state": "ready", "feature_enabled": True},
        )
        self.assertEqual(200, staged.status_code, staged.text)
        self.assertEqual("ready", staged.json()["state"])
        self.assertTrue(staged.json()["feature_enabled"])

        listed = self.client.get("/api/platform/tenant-schemas", headers=headers)
        self.assertEqual(200, listed.status_code, listed.text)
        self.assertIn(self.business_id, [item["business_id"] for item in listed.json()["items"]])

    def test_platform_admin_can_manage_plan_and_subscription(self):
        token = self.login("platform-admin@test", "platform-password")
        headers = {"Authorization": f"Bearer {token}"}
        plan = self.client.post(
            "/api/platform/plans",
            headers=headers,
            json={
                "code": "platform-pro",
                "name": "Platform Pro",
                "price": "199000",
                "max_users": 10,
                "max_channels": 5,
                "max_documents": 50,
                "max_rag_chunks": 1000,
                "max_ai_calls": 5000,
                "max_ai_cost": "500",
            },
        )
        self.assertEqual(201, plan.status_code, plan.text)
        plan_id = plan.json()["id"]
        subscribed = self.client.put(
            f"/api/platform/shops/{self.business_id}/subscription",
            headers=headers,
            json={"plan_id": plan_id, "status": "active", "auto_renew": True},
        )
        self.assertEqual(200, subscribed.status_code, subscribed.text)
        self.assertEqual("platform-pro", subscribed.json()["plan_code"])
        usage = self.client.get(f"/api/platform/shops/{self.business_id}/usage", headers=headers)
        self.assertEqual(5000, usage.json()["limits"]["ai_calls"])
        payment = self.client.post(
            f"/api/platform/shops/{self.business_id}/payments",
            headers=headers,
            json={
                "subscription_id": subscribed.json()["id"],
                "amount": "199000",
                "currency": "VND",
                "provider": "manual",
                "provider_transaction_id": "platform-tx-1",
                "status": "paid",
            },
        )
        self.assertEqual(201, payment.status_code, payment.text)
        replay = self.client.post(
            f"/api/platform/shops/{self.business_id}/payments",
            headers=headers,
            json={
                "subscription_id": subscribed.json()["id"],
                "amount": "199000",
                "currency": "VND",
                "provider": "manual",
                "provider_transaction_id": "platform-tx-1",
                "status": "paid",
            },
        )
        self.assertEqual(200, replay.status_code, replay.text)
        self.assertEqual(payment.json()["id"], replay.json()["id"])

    def test_subscription_rejects_an_impossible_billing_period(self):
        token = self.login("platform-admin@test", "platform-password")
        headers = {"Authorization": f"Bearer {token}"}
        plan = self.client.post(
            "/api/platform/plans",
            headers=headers,
            json={"code": "invalid-period-plan", "name": "Invalid Period", "price": "10"},
        )
        self.assertEqual(201, plan.status_code, plan.text)
        response = self.client.put(
            f"/api/platform/shops/{self.other_business_id}/subscription",
            headers=headers,
            json={
                "plan_id": plan.json()["id"],
                "status": "active",
                "starts_at": "2026-09-30T00:00:00Z",
                "ends_at": "2026-09-01T00:00:00Z",
            },
        )
        self.assertEqual(422, response.status_code, response.text)

    def test_pending_payment_can_advance_once_but_conflicting_replay_is_rejected(self):
        with Session(self.engine) as db:
            plan = ServicePlan(code="payment-state-plan", name="Payment State", price=Decimal("100"))
            db.add(plan)
            db.flush()
            subscription = Subscription(business_id=self.business_id, plan_id=plan.id, status="pending")
            db.add(subscription)
            db.commit()
            subscription_id = subscription.id

        headers = {"Authorization": f"Bearer {self.login('platform-admin@test', 'platform-password')}"}
        pending = self.client.post(
            f"/api/platform/shops/{self.business_id}/payments",
            headers=headers,
            json={"subscription_id": subscription_id, "amount": "100", "currency": "VND", "provider": "manual", "provider_transaction_id": "state-tx-1", "status": "pending"},
        )
        self.assertEqual(201, pending.status_code, pending.text)
        paid = self.client.post(
            f"/api/platform/shops/{self.business_id}/payments",
            headers=headers,
            json={"subscription_id": subscription_id, "amount": "100", "currency": "vnd", "provider": "MANUAL", "provider_transaction_id": " state-tx-1 ", "status": "paid"},
        )
        self.assertEqual(200, paid.status_code, paid.text)
        self.assertEqual("paid", paid.json()["status"])
        with Session(self.engine) as db:
            self.assertEqual("active", db.get(Subscription, subscription_id).status)
        conflict = self.client.post(
            f"/api/platform/shops/{self.business_id}/payments",
            headers=headers,
            json={"subscription_id": subscription_id, "amount": "999", "currency": "VND", "provider": "manual", "provider_transaction_id": "state-tx-1", "status": "paid"},
        )
        self.assertEqual(409, conflict.status_code, conflict.text)

    def test_provider_errors_are_classified_without_returning_payload_or_message(self):
        with Session(self.engine) as db:
            db.add(
                PlatformProviderIncident(
                    business_id=self.business_id,
                    channel_id=7,
                    channel_type="telegram",
                    event_type="message",
                    status="failed",
                    error_type="rate_limit",
                )
            )
            db.commit()
        headers = {"Authorization": f"Bearer {self.login('platform-admin@test', 'platform-password')}"}
        response = self.client.get(f"/api/platform/provider-errors?business_id={self.business_id}", headers=headers)
        self.assertEqual(200, response.status_code, response.text)
        item = next(row for row in response.json() if row["event_type"] == "message")
        self.assertEqual("rate_limit", item["error_type"])
        serialized = str(item).lower()
        self.assertNotIn("must-not-leak", serialized)
        self.assertNotIn("token abc", serialized)


if __name__ == "__main__":
    unittest.main()
