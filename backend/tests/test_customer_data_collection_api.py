import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.business import Business
from app.models.customer import Customer
from app.models.customer_collection import CustomerVerificationChallenge
from app.services.customer_collection import hash_verification_code
from app.services.customer_identity import resolve_customer


class CustomerDataCollectionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="Collection One", slug="collection-one")
            two = Business(name="Collection Two", slug="collection-two")
            db.add_all([one, two])
            db.flush()
            customer = Customer(
                business_id=one.id,
                channel="facebook",
                external_user_id="customer-1",
                name="Nguyễn Văn A",
            )
            other = Customer(
                business_id=two.id,
                channel="facebook",
                external_user_id="customer-2",
                name="Tenant khác",
            )
            db.add_all([customer, other])
            db.commit()
            cls.business_id = one.id
            cls.other_business_id = two.id
            cls.customer_id = customer.id
            cls.other_customer_id = other.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def headers(self, business_id=None):
        return {"X-Business-Id": str(business_id or self.business_id)}

    def test_contact_is_masked_and_tenant_scoped(self):
        response = self.client.post(
            f"/api/customers/{self.customer_id}/contacts",
            headers=self.headers(),
            json={
                "kind": "email",
                "value": "Nguyen.A@example.com",
                "source": "chat",
                "is_primary": True,
            },
        )
        self.assertEqual(201, response.status_code)
        body = response.json()
        self.assertEqual("email", body["kind"])
        self.assertEqual("n***@example.com", body["masked_value"])
        self.assertNotIn("value_encrypted", body)
        self.assertEqual("unverified", body["verification_status"])

        profile = self.client.get(
            f"/api/customers/{self.customer_id}",
            headers=self.headers(),
        )
        self.assertEqual(200, profile.status_code)
        self.assertEqual("n***@example.com", profile.json()["contacts"][0]["masked_value"])

        hidden = self.client.get(
            f"/api/customers/{self.customer_id}/contacts",
            headers=self.headers(self.other_business_id),
        )
        self.assertEqual(404, hidden.status_code)

    def test_collection_session_progress_and_consent(self):
        created = self.client.post(
            f"/api/customers/{self.customer_id}/collection-sessions",
            headers=self.headers(),
            json={
                "purpose": "order",
                "required_fields": ["name", "phone", "address"],
                "source_channel": "facebook",
            },
        )
        self.assertEqual(201, created.status_code)
        session_id = created.json()["id"]

        progressed = self.client.patch(
            f"/api/customers/{self.customer_id}/collection-sessions/{session_id}",
            headers=self.headers(),
            json={
                "collected_fields": {
                    "name": "Nguyễn Văn A",
                    "phone": "+84901234567",
                    "address": "1 Nguyễn Huệ, Q1",
                },
                "current_field": None,
                "status": "completed",
            },
        )
        self.assertEqual(200, progressed.status_code)
        self.assertEqual("completed", progressed.json()["status"])

        consent = self.client.post(
            f"/api/customers/{self.customer_id}/consents",
            headers=self.headers(),
            json={
                "purpose": "order_processing",
                "status": "granted",
                "source_channel": "facebook",
                "policy_version": "2026-09",
            },
        )
        self.assertEqual(201, consent.status_code)
        self.assertEqual("granted", consent.json()["status"])

    def test_verification_challenge_stores_only_hash_and_can_verify(self):
        contact = self.client.post(
            f"/api/customers/{self.customer_id}/contacts",
            headers=self.headers(),
            json={"kind": "phone", "value": "+84 901 234 567", "source": "chat"},
        ).json()
        challenge = self.client.post(
            f"/api/customers/{self.customer_id}/contacts/{contact['id']}/verification-challenges",
            headers=self.headers(),
            json={"channel": "sms"},
        )
        self.assertEqual(202, challenge.status_code)
        self.assertNotIn("code", challenge.json())

        with Session(self.engine) as db:
            row = db.get(CustomerVerificationChallenge, challenge.json()["id"])
            row.code_hash = hash_verification_code("123456")
            row.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=5)
            db.commit()

        verified = self.client.post(
            f"/api/customers/{self.customer_id}/contacts/{contact['id']}/verification-challenges/{challenge.json()['id']}/verify",
            headers=self.headers(),
            json={"code": "123456"},
        )
        self.assertEqual(200, verified.status_code)
        self.assertEqual("verified", verified.json()["verification_status"])

        with Session(self.engine) as db:
            actions = db.query(AuditLog).filter(
                AuditLog.business_id == self.business_id,
                AuditLog.resource_type == "customer_contact",
            ).count()
            self.assertGreaterEqual(actions, 1)
            resolved = resolve_customer(
                db,
                self.business_id,
                "instagram",
                "same-person-instagram",
                phone="0901234567",
            )
            self.assertEqual(self.customer_id, resolved.id)


if __name__ == "__main__":
    unittest.main()
