import unittest
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business, ServicePlan
from app.models.channel import Channel
from app.models.sales import Product
from app.models.inventory import StockMovement
from app.models.audit_log import AuditLog
from app.services.channel_credentials import decrypt_token
from app.core.config import settings


class OnboardingApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Business.metadata.create_all(cls.engine)

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

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
                db.query(AuditLog).filter(AuditLog.action == "onboarding_channel_connected").count(),
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


if __name__ == "__main__":
    unittest.main()
