import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.passwords import hash_password
from app.db.dependencies import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.auth_session import AuthSession
from app.models.business import Business, User


class AuthSecurityControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Security Shop", slug="security-shop")
            db.add(business)
            db.flush()
            owner = User(
                business_id=business.id,
                full_name="Security Owner",
                email="security-owner@test",
                role="owner",
                password_hash=hash_password("security-password"),
            )
            other = User(
                business_id=business.id,
                full_name="Security Other",
                email="security-other@test",
                role="agent",
                password_hash=hash_password("other-password"),
            )
            db.add_all([owner, other])
            db.commit()
            cls.business_id = business.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def login(self, email="security-owner@test", password="security-password", device="Laptop"):
        response = self.client.post(
            "/api/auth/login",
            headers={"X-Business-Id": str(self.business_id), "User-Agent": "test-agent", "X-Device-Label": device},
            json={"email": email, "password": password},
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def test_session_metadata_is_hashed_and_owner_can_revoke_it(self):
        body = self.login()
        token = body["access_token"]
        headers = {"Authorization": f"Bearer {token}", "X-Business-Id": str(self.business_id)}
        sessions = self.client.get("/api/auth/sessions", headers=headers)
        self.assertEqual(200, sessions.status_code, sessions.text)
        session = sessions.json()[0]
        self.assertEqual("Laptop", session["device_label"])
        self.assertNotIn("test-agent", str(session))
        self.assertEqual(204, self.client.post(f"/api/auth/sessions/{session['id']}/revoke", headers=headers).status_code)
        self.assertEqual(401, self.client.get("/api/auth/me", headers=headers).status_code)

    def test_mfa_prepare_returns_provisioning_payload_without_storing_raw_secret(self):
        body = self.login()
        headers = {"Authorization": f"Bearer {body['access_token']}", "X-Business-Id": str(self.business_id)}
        prepared = self.client.post("/api/auth/mfa/prepare", headers=headers)
        self.assertEqual(200, prepared.status_code, prepared.text)
        self.assertEqual("prepared", prepared.json()["status"])
        self.assertIn("otpauth://", prepared.json()["provisioning_uri"])
        with Session(self.engine) as db:
            user = db.scalar(select(User).where(User.email == "security-owner@test"))
            self.assertEqual("prepared", user.mfa_status)
            self.assertNotEqual(prepared.json()["provisioning_uri"], user.mfa_secret_encrypted)
            audit = db.scalar(select(AuditLog).where(AuditLog.action == "mfa_prepared").order_by(AuditLog.id.desc()))
            self.assertNotIn("otpauth://", str(audit.metadata_ if audit else {}))


if __name__ == "__main__":
    unittest.main()
