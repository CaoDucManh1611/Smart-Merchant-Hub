import unittest
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.auth.dependencies import issue_token, token_hash
from app.auth.passwords import hash_password
from app.database.platform_session import get_platform_db
from app.database.bases import PlatformBase, TenantBase
from app.db.dependencies import get_db
from app.main import app
from app.models.auth_session import AuthSession
from app.models.business import Business, ServicePlan, Subscription, User
from app.models.signup import SignupEmailChallenge
from app.models.channel import Channel
from app.models.sales import Product
from app.models.inventory import StockMovement
from app.models.audit_log import AuditLog
from app.services.channel_credentials import decrypt_token
from app.core.config import settings
from app.services.otp_delivery import OtpDeliveryResult


class OnboardingApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._environment = settings.ENVIRONMENT
        settings.ENVIRONMENT = "test"
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Business.metadata.create_all(cls.engine)
        PlatformBase.metadata.create_all(cls.engine)
        TenantBase.metadata.create_all(cls.engine)

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_platform_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        settings.ENVIRONMENT = cls._environment

    def test_public_onboarding_creates_shop_owner_and_subscription(self):
        plans = self.client.get("/api/onboarding/plans")
        self.assertEqual(200, plans.status_code, plans.text)
        self.assertGreaterEqual(len(plans.json()), 3)
        response = self.client.post(
            "/api/onboarding/shops",
            json={
                "shop_name": "Onboarding Shop",
                "owner_name": "Owner One",
                "owner_email": "owner@onboarding.test",
                "password": "strong-pass-1",
                "plan_code": "starter",
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        body = response.json()
        self.assertEqual("starter", body["subscription"]["plan_code"])
        self.assertNotIn("password", body)
        me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        self.assertEqual(200, me.status_code, me.text)
        self.assertEqual(body["business_id"], me.json()["business_id"])

    def test_regular_shop_member_can_read_provisioning_status(self):
        with Session(self.engine) as db:
            business = Business(name="Member Status Shop", slug="member-status-shop")
            plan = ServicePlan(code="member-status-plan", name="Member Status Plan", price=Decimal("0"))
            db.add_all([business, plan])
            db.flush()
            db.add(Subscription(business_id=business.id, plan_id=plan.id, status="active"))
            member = User(
                business_id=business.id,
                full_name="Shop Agent",
                email="member-status@onboarding.test",
                password_hash=hash_password("member-status-pass-1"),
                role="agent",
            )
            db.add(member)
            db.flush()
            token, expires_at = issue_token(member.id, business_id=business.id, role=member.role)
            db.add(AuthSession(user_id=member.id, token_hash=token_hash(token), expires_at=expires_at, mfa_verified=True))
            db.commit()
            business_id = business.id

        response = self.client.get(
            f"/api/onboarding/shops/{business_id}/provision",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(business_id, response.json()["business_id"])

    def test_plan_purchase_rejects_channels_above_package_limit(self):
        created = self.client.post(
            "/api/onboarding/shops",
            json={
                "shop_name": "Starter Channel Limit",
                "owner_name": "Starter Owner",
                "owner_email": "starter-channel-limit@onboarding.test",
                "password": "strong-pass-1",
                "plan_code": "starter",
            },
        )
        self.assertEqual(201, created.status_code, created.text)
        token = created.json()["access_token"]
        response = self.client.post(
            f"/api/onboarding/shops/{created.json()['business_id']}/subscription/purchase",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "plan_code": "starter",
                "channels": ["Telegram", "Zalo"],
            },
        )
        self.assertEqual(422, response.status_code, response.text)
        detail = response.json()["detail"]
        self.assertEqual("plan_channel_limit", detail["code"])
        self.assertEqual(1, detail["max_channels"])

    def test_duplicate_email_is_rejected_and_slug_is_unique(self):
        first = self.client.post(
            "/api/onboarding/shops",
            json={"shop_name": "Duplicate A", "owner_name": "A Owner", "owner_email": "same@onboarding.test", "password": "strong-pass-1"},
        )
        self.assertEqual(201, first.status_code, first.text)
        duplicate = self.client.post(
            "/api/onboarding/shops",
            json={"shop_name": "Duplicate B", "owner_name": "B Owner", "owner_email": "same@onboarding.test", "password": "strong-pass-1"},
        )
        self.assertEqual(409, duplicate.status_code, duplicate.text)

    def test_direct_shop_endpoint_requires_verified_signup_outside_test_mode(self):
        with patch.object(settings, "ENVIRONMENT", "development"):
            response = self.client.post(
                "/api/onboarding/shops",
                json={
                    "shop_name": "OTP Required Shop",
                    "owner_name": "OTP Required Owner",
                    "owner_email": "otp-required@onboarding.test",
                    "password": "Strong-pass-2026",
                },
            )

        self.assertEqual(410, response.status_code, response.text)
        self.assertIn("OTP", response.json()["detail"])

    def test_email_otp_signup_creates_shop_only_after_verification(self):
        request_payload = {
            "owner_name": "OTP Owner",
            "email": "otp-signup@onboarding.test",
            "shop_name": "OTP Signup Shop",
            "password": "strong-pass-1",
        }
        with patch("app.api.onboarding.generate_verification_code", return_value="123456"), patch(
            "app.api.onboarding.deliver_otp",
            return_value=OtpDeliveryResult(provider="smtp", delivered=True),
        ):
            requested = self.client.post("/api/onboarding/signup/request", json=request_payload)
        self.assertEqual(202, requested.status_code, requested.text)
        with Session(self.engine) as db:
            challenge = db.query(SignupEmailChallenge).filter(SignupEmailChallenge.email == request_payload["email"]).one()
            self.assertNotEqual("123456", challenge.code_hash)
            self.assertEqual(0, db.query(Business).filter(Business.name == request_payload["shop_name"]).count())

        wrong = self.client.post(
            "/api/onboarding/signup/verify",
            json={"email": request_payload["email"], "otp": "000000"},
        )
        self.assertEqual(422, wrong.status_code, wrong.text)
        with patch("app.api.onboarding._start_platform_provisioning", return_value="ready"):
            verified = self.client.post(
                "/api/onboarding/signup/verify",
                json={"email": request_payload["email"], "otp": "123456"},
            )
        self.assertEqual(201, verified.status_code, verified.text)
        self.assertEqual("demo", verified.json()["subscription"]["plan_code"])
        self.assertNotIn("password", verified.json())
        with Session(self.engine) as db:
            self.assertEqual(1, db.query(Business).filter(Business.name == request_payload["shop_name"]).count())
            self.assertEqual("verified", db.query(SignupEmailChallenge).filter(SignupEmailChallenge.email == request_payload["email"]).one().status)

    def test_invalid_email_and_inactive_paid_subscription_are_rejected(self):
        invalid = self.client.post(
            "/api/onboarding/shops",
            json={"shop_name": "Invalid Email", "owner_name": "Invalid Owner", "owner_email": "not-an-email", "password": "strong-pass-1"},
        )
        self.assertEqual(422, invalid.status_code, invalid.text)

        paid = self.client.post(
            "/api/onboarding/shops",
            json={"shop_name": "Paid Pending", "owner_name": "Paid Owner", "owner_email": "paid@onboarding.test", "password": "strong-pass-1", "plan_code": "growth"},
        )
        self.assertEqual(201, paid.status_code, paid.text)
        self.assertEqual("pending", paid.json()["subscription"]["status"])
        blocked = self.client.post(
            f"/api/onboarding/shops/{paid.json()['business_id']}/products/import",
            headers={"Authorization": f"Bearer {paid.json()['access_token']}"},
            json={"items": [{"sku": "PENDING-1", "name": "Must wait for payment"}]},
        )
        self.assertEqual(402, blocked.status_code, blocked.text)
        self.assertEqual("subscription_inactive", blocked.json()["detail"]["code"])

    def test_paid_plan_request_waits_for_platform_admin_approval(self):
        created = self.client.post(
            "/api/onboarding/shops",
            json={
                "shop_name": "Approval Queue Shop",
                "owner_name": "Approval Owner",
                "owner_email": "approval-queue@onboarding.test",
                "password": "strong-pass-1",
            },
        ).json()
        request = self.client.post(
            f"/api/onboarding/shops/{created['business_id']}/subscription/purchase",
            headers={"Authorization": f"Bearer {created['access_token']}"},
            json={
                "plan_code": "growth",
                "service_type": "chatbot",
                "contact_name": "Shop Contact",
                "contact_email": "contact@shop.test",
                "contact_phone": "0901234567",
                "shop_name": "Shop Display Name",
                "channels": ["Facebook", "Instagram"],
                "notes": "Please contact after 5pm.",
            },
        )
        self.assertEqual(200, request.status_code, request.text)
        self.assertEqual("pending", request.json()["status"])
        repeated = self.client.post(
            f"/api/onboarding/shops/{created['business_id']}/subscription/purchase",
            headers={"Authorization": f"Bearer {created['access_token']}"},
            json={
                "plan_code": "growth",
                "service_type": "chatbot",
                "contact_name": "Updated Contact",
                "contact_email": "updated@shop.test",
                "contact_phone": "0907654321",
                "shop_name": "Updated Shop Name",
                "channels": ["Telegram", "Zalo"],
                "notes": "Latest request details.",
            },
        )
        self.assertEqual(200, repeated.status_code, repeated.text)
        self.assertEqual(request.json()["id"], repeated.json()["id"])
        with Session(self.engine) as db:
            subscription = db.query(Subscription).filter(
                Subscription.business_id == created["business_id"],
            ).order_by(Subscription.id.desc()).first()
            self.assertIsNotNone(subscription)
            self.assertEqual("pending", subscription.status)
            self.assertEqual("chatbot", subscription.service_type)
            audit_events = db.query(AuditLog).filter(
                AuditLog.business_id == created["business_id"],
                AuditLog.action == "subscription_request_submitted",
                AuditLog.resource_id == str(subscription.id),
            ).order_by(AuditLog.id.asc()).all()
            self.assertEqual(2, len(audit_events))
            self.assertEqual(
                {
                    "contact_name": "Updated Contact",
                    "contact_email": "updated@shop.test",
                    "contact_phone": "0907654321",
                    "shop_name": "Updated Shop Name",
                    "channels": ["Telegram", "Zalo"],
                    "notes": "Latest request details.",
                },
                audit_events[-1].metadata_["request_details"],
            )

    def test_shop_agent_can_request_paid_plan_but_cannot_activate_demo(self):
        created = self.client.post(
            "/api/onboarding/shops",
            json={
                "shop_name": "Agent Approval Shop",
                "owner_name": "Agent Approval Owner",
                "owner_email": "agent-approval@onboarding.test",
                "password": "strong-pass-1",
            },
        ).json()
        with Session(self.engine) as db:
            agent = User(
                business_id=created["business_id"],
                full_name="Shop Agent",
                email="agent@agent-approval.test",
                role="business_agent",
                is_active=True,
            )
            db.add(agent)
            db.flush()
            token, expires_at = issue_token(
                agent.id,
                business_id=agent.business_id,
                role=agent.role,
            )
            db.add(AuthSession(
                user_id=agent.id,
                token_hash=token_hash(token),
                expires_at=expires_at,
                mfa_verified=True,
            ))
            db.commit()

        headers = {"Authorization": f"Bearer {token}"}
        request = self.client.post(
            f"/api/onboarding/shops/{created['business_id']}/subscription/purchase",
            headers=headers,
            json={"plan_code": "growth", "service_type": "chatbot"},
        )
        self.assertEqual(200, request.status_code, request.text)
        self.assertEqual("pending", request.json()["status"])

        demo = self.client.post(
            f"/api/onboarding/shops/{created['business_id']}/subscription/purchase",
            headers=headers,
            json={"plan_code": "demo"},
        )
        self.assertEqual(403, demo.status_code, demo.text)

    def test_owner_can_connect_encrypted_channel_and_import_products(self):
        settings.CHANNEL_ENCRYPTION_KEY = "test-onboarding-channel-key"
        created = self.client.post(
            "/api/onboarding/shops",
            json={"shop_name": "Connect Shop", "owner_name": "Connect Owner", "owner_email": "connect@onboarding.test", "password": "strong-pass-1"},
        ).json()
        headers = {"Authorization": f"Bearer {created['access_token']}"}
        channel = self.client.post(
            f"/api/onboarding/shops/{created['business_id']}/channels",
            headers=headers,
            json={
                "channel_type": "telegram",
                "external_account_id": "bot-connect",
                "name": "Telegram Bot",
                "access_token": "telegram-secret",
                "config": {
                    "webhook_secret": "webhook-secret",
                    "display_name": "safe",
                    "nested": {"api_key": "must-not-be-stored", "label": "visible"},
                },
            },
        )
        self.assertEqual(200, channel.status_code, channel.text)
        self.assertNotIn("access_token", channel.json())
        with Session(self.engine) as db:
            row = db.query(Channel).filter(Channel.business_id == created["business_id"]).one()
            self.assertIsNone(row.access_token)
            self.assertEqual("telegram-secret", decrypt_token(row.access_token_encrypted, settings.CHANNEL_ENCRYPTION_KEY))
            self.assertNotIn("webhook_secret", row.config)
            self.assertIn("webhook_secret_encrypted", row.config)
            self.assertNotIn("api_key", row.config["nested"])
            self.assertEqual("visible", row.config["nested"]["label"])
            self.assertEqual(
                1,
                db.query(AuditLog).filter(
                    AuditLog.business_id == created["business_id"],
                    AuditLog.action == "onboarding_channel_connected",
                ).count(),
            )
        imported = self.client.post(
            f"/api/onboarding/shops/{created['business_id']}/products/import",
            headers=headers,
            json={"items": [{"sku": "SKU-1", "name": "Product 1", "price": "100", "stock_quantity": 4}]},
        )
        self.assertEqual(200, imported.status_code, imported.text)
        self.assertEqual(1, imported.json()["imported"])
        self.assertEqual(1, self.client.post(
            f"/api/onboarding/shops/{created['business_id']}/products/import",
            headers=headers,
            json={"items": [{"sku": "sku-1", "name": "Product 1 Updated", "price": "200", "stock_quantity": 7}]},
        ).json()["updated"])
        with Session(self.engine) as db:
            product = db.query(Product).filter(Product.business_id == created["business_id"], Product.sku == "SKU-1").one()
            self.assertEqual(Decimal("200.00"), product.price)
            self.assertEqual(7, product.stock_quantity)
            movements = db.query(StockMovement).filter(StockMovement.product_id == product.id).order_by(StockMovement.id).all()
            self.assertEqual([4, 3], [movement.quantity for movement in movements])
            self.assertEqual("onboarding_reconcile", movements[-1].movement_type)

    def test_manual_bot_connection_requires_webhook_secret(self):
        settings.CHANNEL_ENCRYPTION_KEY = "test-onboarding-channel-key"
        created = self.client.post(
            "/api/onboarding/shops",
            json={"shop_name": "Secret Required", "owner_name": "Owner", "owner_email": "secret-required@onboarding.test", "password": "strong-pass-1"},
        ).json()
        response = self.client.post(
            f"/api/onboarding/shops/{created['business_id']}/channels",
            headers={"Authorization": f"Bearer {created['access_token']}"},
            json={
                "channel_type": "telegram",
                "external_account_id": "bot-without-secret",
                "name": "Telegram Bot",
                "access_token": "telegram-secret",
            },
        )
        self.assertEqual(422, response.status_code, response.text)
        self.assertEqual("webhook_secret_required", response.json()["detail"]["code"])

    def test_verified_telegram_connection_discovers_bot_and_registers_webhook(self):
        settings.CHANNEL_ENCRYPTION_KEY = "test-onboarding-channel-key"
        settings.PUBLIC_BASE_URL = "https://crm.example.test"
        created = self.client.post(
            "/api/onboarding/shops",
            json={"shop_name": "Telegram Verify", "owner_name": "Verify Owner", "owner_email": "verify-telegram@onboarding.test", "password": "strong-pass-1"},
        ).json()
        headers = {"Authorization": f"Bearer {created['access_token']}"}
        calls = []

        class FakeResponse:
            def __init__(self, body):
                self._body = body

            def raise_for_status(self):
                return None

            def json(self):
                return self._body

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith("/getMe"):
                return FakeResponse({"ok": True, "result": {"id": 12345, "first_name": "Verify Bot", "username": "verify_bot"}})
            if url.endswith("/setWebhook"):
                return FakeResponse({"ok": True, "result": {"url": kwargs["json"]["url"]}})
            if url.endswith("/getWebhookInfo"):
                return FakeResponse({"ok": True, "result": {"url": "https://crm.example.test/api/webhooks/telegram-verify"}})
            raise AssertionError(f"unexpected provider call: {url}")

        with patch("httpx.post", side_effect=fake_post):
            response = self.client.post(
                f"/api/onboarding/shops/{created['business_id']}/channels/verify",
                headers=headers,
                json={"channel_type": "telegram", "access_token": "telegram-verify-token"},
            )
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual("telegram", body["channel_type"])
        self.assertEqual("12345", body["external_account_id"])
        self.assertEqual("Verify Bot", body["name"])
        self.assertEqual("connected", body["webhook_status"])
        self.assertEqual(3, len(calls))
        self.assertTrue(calls[1][0].endswith("/setWebhook"))
        self.assertEqual("https://crm.example.test/api/webhooks/telegram-verify", calls[1][1]["json"]["url"])
        self.assertTrue(calls[1][1]["json"]["secret_token"])
        with Session(self.engine) as db:
            row = db.query(Channel).filter(Channel.business_id == created["business_id"]).one()
            self.assertEqual("12345", row.external_account_id)
            self.assertEqual("webhook_secret_encrypted", next(key for key in row.config if key.endswith("_encrypted")))
            self.assertNotIn("telegram-verify-token", str(row.config))

    def test_verified_zalo_connection_discovers_bot_and_registers_webhook(self):
        settings.CHANNEL_ENCRYPTION_KEY = "test-onboarding-channel-key"
        settings.PUBLIC_BASE_URL = "https://crm.example.test"
        created = self.client.post(
            "/api/onboarding/shops",
            json={"shop_name": "Zalo Verify", "owner_name": "Verify Owner", "owner_email": "verify-zalo@onboarding.test", "password": "strong-pass-1"},
        ).json()
        headers = {"Authorization": f"Bearer {created['access_token']}"}

        class FakeResponse:
            def __init__(self, body):
                self._body = body

            def raise_for_status(self):
                return None

            def json(self):
                return self._body

        def fake_post(url, **kwargs):
            if url.endswith("/getMe"):
                return FakeResponse({"ok": True, "result": {"id": "zalo-9988", "account_name": "Bot Zalo Verify"}})
            if url.endswith("/setWebhook"):
                return FakeResponse({"ok": True, "result": {"url": kwargs["json"]["url"]}})
            if url.endswith("/getWebhookInfo"):
                return FakeResponse({"ok": True, "result": {"url": "https://crm.example.test/api/webhooks/zalo-verify"}})
            raise AssertionError(f"unexpected provider call: {url}")

        with patch("httpx.post", side_effect=fake_post):
            response = self.client.post(
                f"/api/onboarding/shops/{created['business_id']}/channels/verify",
                headers=headers,
                json={"channel_type": "zalo", "access_token": "zalo-verify-token"},
            )
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual("zalo", body["channel_type"])
        self.assertEqual("zalo-9988", body["external_account_id"])
        self.assertEqual("Bot Zalo Verify", body["name"])
        self.assertEqual("connected", body["webhook_status"])

    def test_bot_connection_status_and_disconnect_hide_secrets_and_preserve_history(self):
        settings.CHANNEL_ENCRYPTION_KEY = "test-onboarding-channel-key"
        created = self.client.post(
            "/api/onboarding/shops",
            json={"shop_name": "Bot Lifecycle", "owner_name": "Lifecycle Owner", "owner_email": "bot-lifecycle@onboarding.test", "password": "strong-pass-1"},
        ).json()
        headers = {"Authorization": f"Bearer {created['access_token']}"}
        connected = self.client.post(
            f"/api/onboarding/shops/{created['business_id']}/channels",
            headers=headers,
            json={
                "channel_type": "telegram",
                "external_account_id": "bot-lifecycle",
                "name": "Lifecycle Bot",
                "access_token": "telegram-lifecycle-secret",
                "config": {"webhook_secret": "lifecycle-webhook-secret", "webhook_url": "https://crm.example.test/api/webhooks/telegram"},
            },
        )
        self.assertEqual(200, connected.status_code, connected.text)
        channel_id = connected.json()["id"]

        listed = self.client.get(
            f"/api/onboarding/shops/{created['business_id']}/channels",
            headers=headers,
        )
        self.assertEqual(200, listed.status_code, listed.text)
        self.assertEqual(1, len(listed.json()))
        self.assertEqual("Lifecycle Bot", listed.json()[0]["name"])
        self.assertNotIn("access_token", listed.text)
        self.assertNotIn("lifecycle-webhook-secret", listed.text)

        disconnected = self.client.delete(
            f"/api/onboarding/shops/{created['business_id']}/channels/{channel_id}",
            headers=headers,
        )
        self.assertEqual(200, disconnected.status_code, disconnected.text)
        self.assertEqual(channel_id, disconnected.json()["channel_id"])
        remaining = self.client.get(
            f"/api/onboarding/shops/{created['business_id']}/channels",
            headers=headers,
        )
        self.assertEqual(200, remaining.status_code, remaining.text)
        self.assertEqual(1, len(remaining.json()))
        self.assertEqual("disconnected", remaining.json()[0]["status"])
        with Session(self.engine) as db:
            row = db.get(Channel, channel_id)
            self.assertEqual("disconnected", row.status)
            self.assertEqual(
                1,
                db.query(AuditLog).filter(
                    AuditLog.business_id == created["business_id"],
                    AuditLog.action == "onboarding_bot_disconnected",
                ).count(),
            )


if __name__ == "__main__":
    unittest.main()
