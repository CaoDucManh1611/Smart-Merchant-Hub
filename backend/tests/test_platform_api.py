import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.passwords import hash_password
from app.core.config import settings
from app.database.bases import PlatformBase, TenantBase
from app.database.platform_session import get_platform_db
from app.db.dependencies import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.business import Business, Payment, ServicePlan, Subscription, User
from app.models.platform_control import PlatformAudit, PlatformProviderIncident
from app.models.saas import PlatformMembership


class PlatformApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._allow_legacy_tenant_header = settings.ALLOW_LEGACY_TENANT_HEADER
        settings.ALLOW_LEGACY_TENANT_HEADER = True
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        PlatformBase.metadata.create_all(cls.engine)
        TenantBase.metadata.create_all(cls.engine)
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
        settings.ALLOW_LEGACY_TENANT_HEADER = cls._allow_legacy_tenant_header

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
        headers = {"Authorization": f"Bearer {token}", "X-Business-Id": str(self.business_id)}
        response = self.client.get(
            "/api/platform/shops",
            headers=headers,
        )
        self.assertEqual(403, response.status_code)
        pending_requests = self.client.get("/api/platform/subscription-requests", headers=headers)
        self.assertEqual(403, pending_requests.status_code)

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

    def test_platform_admin_can_list_zero_value_demo_payment(self):
        with Session(self.engine) as db:
            plan = ServicePlan(code="zero-payment-plan", name="Zero Payment Plan", price=Decimal("0"))
            db.add(plan)
            db.flush()
            subscription = Subscription(
                business_id=self.business_id,
                plan_id=plan.id,
                status="active",
                service_type="package",
            )
            db.add(subscription)
            db.flush()
            db.add(Payment(
                business_id=self.business_id,
                subscription_id=subscription.id,
                amount=Decimal("0"),
                currency="VND",
                provider="demo",
                provider_transaction_id="demo-zero-payment",
                status="paid",
            ))
            db.commit()

        token = self.login("platform-admin@test", "platform-password")
        response = self.client.get(
            f"/api/platform/shops/{self.business_id}/payments",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(200, response.status_code, response.text)
        demo_payment = next(item for item in response.json() if item["provider_transaction_id"] == "demo-zero-payment")
        self.assertEqual("0.00", demo_payment["amount"])

    def test_platform_admin_can_approve_or_reject_pending_subscription_requests(self):
        requested_at = datetime.now().replace(microsecond=0)
        with Session(self.engine) as db:
            plan = ServicePlan(code="approval-plan", name="Approval Plan", price=Decimal("199000"))
            db.add(plan)
            db.flush()
            previous_submitter = User(
                business_id=self.other_business_id,
                full_name="Previous Submitter",
                email="previous-submit@test",
                role="agent",
            )
            latest_submitter = User(
                business_id=self.other_business_id,
                full_name="Latest Submitter",
                email="latest-submit@test",
                role="agent",
            )
            db.add_all([previous_submitter, latest_submitter])
            db.flush()
            pending = Subscription(
                business_id=self.other_business_id,
                plan_id=plan.id,
                status="pending",
                created_at=requested_at - timedelta(days=3),
            )
            db.add(pending)
            db.flush()
            older_pending = Subscription(
                business_id=self.business_id,
                plan_id=plan.id,
                status="pending",
                created_at=requested_at - timedelta(hours=4),
            )
            db.add(older_pending)
            db.flush()
            older_requester_id = db.scalar(
                select(User.id).where(User.email == "platform-agent@test")
            )
            db.add_all([
                AuditLog(
                    business_id=self.other_business_id,
                    user_id=previous_submitter.id,
                    action="subscription_request_submitted",
                    resource_type="subscription",
                    resource_id=str(pending.id),
                    created_at=requested_at - timedelta(days=2),
                ),
                AuditLog(
                    business_id=self.other_business_id,
                    user_id=latest_submitter.id,
                    action="subscription_request_submitted",
                    resource_type="subscription",
                    resource_id=str(pending.id),
                    metadata_={
                        "request_details": {
                            "contact_name": "Latest Contact",
                            "contact_email": "contact@latest.test",
                            "contact_phone": "0900000000",
                            "shop_name": "Latest Shop Name",
                            "channels": ["Facebook", "Zalo"],
                            "notes": "Latest request note.",
                        },
                    },
                    created_at=requested_at,
                ),
                AuditLog(
                    business_id=self.business_id,
                    user_id=older_requester_id,
                    action="subscription_request_submitted",
                    resource_type="subscription",
                    resource_id=str(older_pending.id),
                    created_at=requested_at - timedelta(hours=3),
                ),
            ])
            db.commit()
            pending_id = pending.id
            older_pending_id = older_pending.id

        headers = {"Authorization": f"Bearer {self.login('platform-admin@test', 'platform-password')}"}
        listed = self.client.get("/api/platform/subscription-requests", headers=headers)
        self.assertEqual(200, listed.status_code, listed.text)
        request_item = next(item for item in listed.json()["items"] if item["subscription_id"] == pending_id)
        request_ids = [item["subscription_id"] for item in listed.json()["items"]]
        self.assertLess(request_ids.index(pending_id), request_ids.index(older_pending_id))
        self.assertEqual(self.other_business_id, request_item["business_id"])
        self.assertEqual("approval-plan", request_item["plan_code"])
        self.assertEqual("pending", request_item["status"])
        self.assertEqual("Latest Submitter", request_item["requester_name"])
        self.assertEqual("latest-submit@test", request_item["requester_email"])
        self.assertEqual(
            requested_at.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
            request_item["requested_at"],
        )
        self.assertEqual("Latest Contact", request_item["contact_name"])
        self.assertEqual("contact@latest.test", request_item["contact_email"])
        self.assertEqual("0900000000", request_item["contact_phone"])
        self.assertEqual("Latest Shop Name", request_item["requested_shop_name"])
        self.assertEqual(["Facebook", "Zalo"], request_item["requested_channels"])
        self.assertEqual("Latest request note.", request_item["request_notes"])

        provisioned = SimpleNamespace(
            business_id=self.other_business_id,
            schema_name=f"tenant_{self.other_business_id}",
            state="active",
            feature_enabled=True,
            tenant_revision="test-revision",
            migration_error=None,
        )
        with patch("app.api.platform.provision_shop", return_value=provisioned):
            approved = self.client.post(
                f"/api/platform/subscription-requests/{pending_id}/approve",
                headers=headers,
            )
        self.assertEqual(200, approved.status_code, approved.text)
        self.assertEqual("active", approved.json()["subscription"]["status"])
        self.assertEqual("active", approved.json()["provisioning"]["state"])
        with Session(self.engine) as db:
            self.assertEqual("active", db.get(Subscription, pending_id).status)
            audit = db.scalar(select(AuditLog).where(
                AuditLog.business_id == self.other_business_id,
                AuditLog.action == "platform_subscription_approved",
            ))
            self.assertIsNotNone(audit)

        with Session(self.engine) as db:
            rejected = Subscription(
                business_id=self.business_id,
                plan_id=db.scalar(select(ServicePlan.id).where(ServicePlan.code == "approval-plan")),
                status="pending",
            )
            db.add(rejected)
            db.commit()
            rejected_id = rejected.id
        declined = self.client.post(
            f"/api/platform/subscription-requests/{rejected_id}/reject",
            headers=headers,
        )
        self.assertEqual(200, declined.status_code, declined.text)
        self.assertEqual("cancelled", declined.json()["status"])

    def test_platform_admin_can_set_a_separate_chatbot_rental_price(self):
        token = self.login("platform-admin@test", "platform-password")
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "code": "chatbot-priced-plan",
            "name": "Chatbot Priced Plan",
            "price": "390000",
            "max_users": 10,
            "max_channels": 2,
            "max_documents": 50,
            "max_rag_chunks": 1000,
            "max_ai_calls": 5000,
            "max_ai_cost": "500",
            "features": {"chatbot_rental_price": 590000},
        }
        created = self.client.post("/api/platform/plans", headers=headers, json=payload)
        self.assertEqual(201, created.status_code, created.text)

        payload["features"] = {"chatbot_rental_price": 650000}
        updated = self.client.patch(
            f"/api/platform/plans/{created.json()['id']}",
            headers=headers,
            json=payload,
        )
        self.assertEqual(200, updated.status_code, updated.text)
        self.assertEqual(650000, int(updated.json()["features"]["chatbot_rental_price"]))

        listed = self.client.get("/api/platform/plans", headers=headers)
        self.assertEqual(200, listed.status_code, listed.text)
        persisted = next(item for item in listed.json() if item["id"] == created.json()["id"])
        self.assertEqual(650000, int(persisted["features"]["chatbot_rental_price"]))

    def test_global_platform_admin_can_update_plan_without_shop_audit_fk(self):
        with Session(self.engine) as db:
            global_admin = User(
                business_id=None,
                full_name="Global Platform Admin",
                email="global-platform-admin@test",
                role="admin",
                password_hash=hash_password("global-platform-password"),
            )
            db.add(global_admin)
            db.flush()
            db.add(PlatformMembership(user_id=global_admin.id))
            db.commit()

        login = self.client.post(
            "/api/auth/login",
            json={"email": "global-platform-admin@test", "password": "global-platform-password"},
        )
        self.assertEqual(200, login.status_code, login.text)
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "code": "global-platform-plan",
            "name": "Global Platform Plan",
            "price": "100000",
            "features": {"chatbot_rental_price": 120000},
        }
        created = self.client.post("/api/platform/plans", headers=headers, json=payload)
        self.assertEqual(201, created.status_code, created.text)

        payload["price"] = "150000"
        updated = self.client.patch(
            f"/api/platform/plans/{created.json()['id']}",
            headers=headers,
            json=payload,
        )
        self.assertEqual(200, updated.status_code, updated.text)
        self.assertEqual("150000.00", updated.json()["price"])

        with Session(self.engine) as db:
            audit = db.scalar(
                select(PlatformAudit).where(
                    PlatformAudit.action == "platform_plan_updated",
                    PlatformAudit.resource_id == str(created.json()["id"]),
                )
            )
            self.assertIsNotNone(audit)

    def test_platform_admin_can_delete_unused_plan_but_protect_used_plan(self):
        token = self.login("platform-admin@test", "platform-password")
        headers = {"Authorization": f"Bearer {token}"}
        deletable = self.client.post(
            "/api/platform/plans",
            headers=headers,
            json={"code": "deletable-plan", "name": "Deletable Plan", "price": "0"},
        )
        self.assertEqual(201, deletable.status_code, deletable.text)
        deleted = self.client.delete(
            f"/api/platform/plans/{deletable.json()['id']}",
            headers=headers,
        )
        self.assertEqual(204, deleted.status_code, deleted.text)
        listed = self.client.get("/api/platform/plans", headers=headers)
        self.assertNotIn("deletable-plan", [item["code"] for item in listed.json()])

        protected = self.client.post(
            "/api/platform/plans",
            headers=headers,
            json={"code": "protected-delete-plan", "name": "Protected Delete Plan", "price": "100"},
        )
        self.assertEqual(201, protected.status_code, protected.text)
        with Session(self.engine) as db:
            db.add(Subscription(
                business_id=self.business_id,
                plan_id=protected.json()["id"],
                service_type="package",
                status="cancelled",
            ))
            db.commit()
        blocked = self.client.delete(
            f"/api/platform/plans/{protected.json()['id']}",
            headers=headers,
        )
        self.assertEqual(409, blocked.status_code, blocked.text)

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
