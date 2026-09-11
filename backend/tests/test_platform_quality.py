import base64
import hashlib
import hmac
import struct
import time
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.passwords import hash_password
from app.db.dependencies import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.business import Business, User
from app.services.provider_circuit_breaker import ProviderCircuitBreaker, ProviderCircuitOpen
from app.services.audit_service import record_audit


def _totp(secret: str, timestamp: int | None = None) -> str:
    timestamp = int(time.time() if timestamp is None else timestamp)
    counter = timestamp // 30
    digest = hmac.new(
        base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8)),
        struct.pack(">Q", counter),
        hashlib.sha1,
    ).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{value:06d}"


class PlatformQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Platform Quality", slug="platform-quality")
            db.add(business)
            db.flush()
            owner = User(
                business_id=business.id,
                full_name="Platform Owner",
                email="platform-owner@test",
                role="owner",
                password_hash=hash_password("platform-password"),
            )
            db.add(owner)
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

    def login(self):
        response = self.client.post(
            "/api/auth/login",
            headers={"X-Business-Id": str(self.business_id), "User-Agent": "quality-test"},
            json={"email": "platform-owner@test", "password": "platform-password"},
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def test_mfa_enrollment_verification_enables_and_unverified_session_is_blocked(self):
        body = self.login()
        headers = {"Authorization": f"Bearer {body['access_token']}", "X-Business-Id": str(self.business_id)}
        prepared = self.client.post("/api/auth/mfa/prepare", headers=headers)
        self.assertEqual(200, prepared.status_code, prepared.text)
        secret = prepared.json()["provisioning_uri"].split("secret=", 1)[1].split("&", 1)[0]
        verified = self.client.post("/api/auth/mfa/verify", headers=headers, json={"code": _totp(secret)})
        self.assertEqual(200, verified.status_code, verified.text)
        self.assertEqual("enabled", verified.json()["status"])

        second = self.login()
        unverified_headers = {"Authorization": f"Bearer {second['access_token']}", "X-Business-Id": str(self.business_id)}
        blocked = self.client.get("/api/auth/me", headers=unverified_headers)
        self.assertEqual(401, blocked.status_code, blocked.text)
        self.assertEqual("mfa_required", blocked.json()["detail"]["code"])
        verified_again = self.client.post("/api/auth/mfa/verify", headers=unverified_headers, json={"code": _totp(secret)})
        self.assertEqual(200, verified_again.status_code, verified_again.text)
        self.assertEqual(200, self.client.get("/api/auth/me", headers=unverified_headers).status_code)

    def test_audit_event_has_stable_event_id_and_actor_type(self):
        with Session(self.engine) as db:
            row = record_audit(db, business_id=self.business_id, user_id=1, action="quality_test", resource_type="test", correlation_id="corr-1")
            db.commit()
            db.refresh(row)
            self.assertTrue(row.event_id)
            self.assertEqual("staff", row.actor_type)
            self.assertEqual("corr-1", row.correlation_id)
            self.assertEqual(row.id, db.scalar(select(AuditLog.id).where(AuditLog.event_id == row.event_id)))

    def test_provider_breaker_opens_and_recovers(self):
        now = [100.0]
        breaker = ProviderCircuitBreaker(failure_threshold=2, recovery_timeout=10, clock=lambda: now[0])
        breaker.record_failure("gemini")
        self.assertEqual("closed", breaker.state("gemini"))
        breaker.record_failure("gemini")
        self.assertEqual("open", breaker.state("gemini"))
        with self.assertRaises(ProviderCircuitOpen):
            breaker.before_call("gemini")
        now[0] = 111.0
        breaker.before_call("gemini")
        self.assertEqual("half_open", breaker.state("gemini"))
        breaker.record_success("gemini")
        self.assertEqual("closed", breaker.state("gemini"))

    def test_ai_evaluation_dashboard_is_tenant_scoped_and_has_quality_sections(self):
        response = self.client.get("/api/experiments/evaluation/dashboard?days=7", headers={"X-Business-Id": str(self.business_id)})
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual(7, body["period_days"])
        self.assertIn("models", body)
        self.assertIn("experiments", body)
        self.assertIn("rag", body)


if __name__ == "__main__":
    unittest.main()
