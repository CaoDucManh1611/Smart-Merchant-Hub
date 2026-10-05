import unittest
from datetime import datetime, timezone
from unittest.mock import patch

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
from app.models.signup import SignupEmailChallenge
from app.services.otp_delivery import OtpDeliveryResult


class AuthSecurityControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        AuditLog.__table__.create(cls.engine, checkfirst=True)
        with Session(cls.engine) as db:
            business = Business(name="Security Shop", slug="security-shop")
            db.add(business)
            db.flush()
            owner = User(
                business_id=business.id,
                full_name="Security Owner",
                email="security-owner@example.test",
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

    def login(self, email="security-owner@example.test", password="security-password", device="Laptop"):
        response = self.client.post(
            "/api/auth/login",
            headers={"X-Business-Id": str(self.business_id), "User-Agent": "test-agent", "X-Device-Label": device},
            json={"email": email, "password": password},
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def restore_password_reset_fixture(self):
        with Session(self.engine) as db:
            user = db.scalar(select(User).where(User.email == "security-owner@example.test"))
            user.password_hash = hash_password("security-password")
            db.query(SignupEmailChallenge).filter_by(purpose="password_reset").delete()
            db.commit()

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
            user = db.scalar(select(User).where(User.email == "security-owner@example.test"))
            self.assertEqual("prepared", user.mfa_status)
            self.assertNotEqual(prepared.json()["provisioning_uri"], user.mfa_secret_encrypted)
            audit = db.scalar(select(AuditLog).where(AuditLog.action == "mfa_prepared").order_by(AuditLog.id.desc()))
            self.assertNotIn("otpauth://", str(audit.metadata_ if audit else {}))

        rejected_code = self.client.post("/api/auth/mfa/verify", headers=headers, json={"code": "000000"})
        self.assertEqual(422, rejected_code.status_code, rejected_code.text)

    def test_password_reset_uses_email_otp_extends_remembered_session_and_revokes_old_sessions(self):
        self.addCleanup(self.restore_password_reset_fixture)
        login_response = self.client.post(
            "/api/auth/login",
            headers={"X-Business-Id": str(self.business_id)},
            json={"email": "security-owner@example.test", "password": "security-password", "remember_me": True},
        )
        self.assertEqual(200, login_response.status_code, login_response.text)
        token = login_response.json()["access_token"]
        expires_at = datetime.fromisoformat(login_response.json()["expires_at"].replace("Z", "+00:00"))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        self.assertGreater((expires_at - datetime.now(timezone.utc)).days, 28)

        with patch("app.api.auth.generate_verification_code", return_value="482913"), patch(
            "app.api.auth.deliver_otp",
            return_value=OtpDeliveryResult(provider="smtp", delivered=True),
        ):
            requested = self.client.post(
                "/api/auth/password-reset/request",
                json={"email": "security-owner@example.test", "shop_slug": "security-shop"},
            )
            self.assertEqual(202, requested.status_code, requested.text)
            challenge = self.client.post(
                "/api/auth/password-reset/complete",
                json={
                    "email": "security-owner@example.test",
                    "shop_slug": "security-shop",
                    "otp": "482913",
                    "new_password": "New-Secure-Password-2026",
                },
            )
        self.assertEqual(200, challenge.status_code, challenge.text)

        with Session(self.engine) as db:
            stored_challenge = db.query(SignupEmailChallenge).filter_by(purpose="password_reset").one()
            self.assertNotEqual("482913", stored_challenge.code_hash)
            self.assertEqual("verified", stored_challenge.status)
        headers = {"Authorization": f"Bearer {token}", "X-Business-Id": str(self.business_id)}
        self.assertEqual(401, self.client.get("/api/auth/me", headers=headers).status_code)
        old_password = self.client.post(
            "/api/auth/login",
            headers={"X-Business-Id": str(self.business_id)},
            json={"email": "security-owner@example.test", "password": "security-password"},
        )
        self.assertEqual(401, old_password.status_code)
        new_password = self.client.post(
            "/api/auth/login",
            headers={"X-Business-Id": str(self.business_id)},
            json={"email": "security-owner@example.test", "password": "New-Secure-Password-2026"},
        )
        self.assertEqual(200, new_password.status_code, new_password.text)


if __name__ == "__main__":
    unittest.main()
