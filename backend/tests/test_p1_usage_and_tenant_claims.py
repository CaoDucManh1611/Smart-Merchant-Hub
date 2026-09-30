import base64
import json
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import issue_token
from app.auth.passwords import hash_password
from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business, User
from app.services.quota_service import quota_snapshot


class P1UsageAndTenantClaimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Usage Shop", slug="usage-shop")
            other = Business(name="Other Usage Shop", slug="other-usage-shop")
            db.add_all([business, other])
            db.flush()
            user = User(business_id=business.id, full_name="Usage Owner", email="usage-owner@test", password_hash=hash_password("usage-pass"), role="owner")
            db.add(user)
            db.commit()
            cls.business_id = business.id
            cls.other_business_id = other.id
        def override_get_db():
            with Session(cls.engine) as db:
                yield db
        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_login_token_contains_and_enforces_current_tenant_and_role_claims(self):
        login = self.client.post("/api/auth/login", headers={"X-Business-Id": str(self.business_id)}, json={"email": "usage-owner@test", "password": "usage-pass"})
        self.assertEqual(200, login.status_code, login.text)
        token = login.json()["access_token"]
        encoded = token.split(".", 1)[0]
        payload = json.loads(base64.urlsafe_b64decode(encoded + "===").decode())
        self.assertEqual(self.business_id, payload["business_id"])
        self.assertEqual("owner", payload["role"])
        response = self.client.get("/api/usage", headers={"Authorization": f"Bearer {token}", "X-Business-Id": str(self.other_business_id)})
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(self.business_id, response.json()["business_id"])

    def test_usage_snapshot_exposes_non_mutating_warning_contract(self):
        with Session(self.engine) as db:
            snapshot = quota_snapshot(db, self.business_id)
            self.assertIn("resources", snapshot)
            self.assertEqual(6, len(snapshot["resources"]))
            self.assertIn("near_limit", snapshot["resources"]["ai_calls"])
        response = self.client.get("/api/usage", headers={"X-Business-Id": str(self.business_id)})
        self.assertEqual(200, response.status_code, response.text)
        self.assertIn("warning_percent", response.json())


if __name__ == "__main__":
    unittest.main()
