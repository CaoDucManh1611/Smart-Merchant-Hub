import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models import Business, Conversation, Customer, Message, Order
from app.models.audit_log import AuditLog


class PrivacyApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            one = Business(name="Privacy One", slug="privacy-one")
            two = Business(name="Privacy Two", slug="privacy-two")
            db.add_all([one, two])
            db.flush()
            customer = Customer(
                business_id=one.id,
                channel="telegram",
                external_user_id="privacy-user",
                name="Người Cần Xóa",
                email="private@example.test",
                phone="0900000000",
                address="Địa chỉ riêng",
            )
            other = Customer(
                business_id=two.id,
                channel="telegram",
                external_user_id="other-user",
                name="Other Tenant",
                email="other@example.test",
            )
            db.add_all([customer, other])
            db.flush()
            conversation = Conversation(business_id=one.id, customer_id=customer.id, channel="telegram")
            db.add(conversation)
            db.flush()
            db.add(Message(conversation_id=conversation.id, channel="telegram", content="Tin nhắn riêng", external_user_id="privacy-user"))
            db.commit()
            self.business_id = one.id
            self.other_business_id = two.id
            self.customer_id = customer.id

        def override_get_db():
            with Session(self.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def headers(self, business_id=None):
        return {"X-Business-Id": str(business_id or self.business_id)}

    def test_export_is_allow_listed_and_tenant_scoped(self):
        response = self.client.post(
            "/api/privacy/export",
            headers=self.headers(),
            json={"request_key": "export-privacy-1"},
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("completed", response.json()["status"])
        self.assertEqual("Người Cần Xóa", response.json()["data"]["customers"][0]["name"])
        self.assertNotIn("Other Tenant", str(response.json()))
        self.assertNotIn("password_hash", str(response.json()))

    def test_anonymize_and_delete_are_idempotent_and_leave_other_tenant_untouched(self):
        anonymized = self.client.post(
            "/api/privacy/anonymize",
            headers=self.headers(),
            json={"request_key": "anonymize-privacy-1"},
        )
        self.assertEqual(200, anonymized.status_code, anonymized.text)
        self.assertEqual("completed", anonymized.json()["status"])
        repeat = self.client.post(
            "/api/privacy/anonymize",
            headers=self.headers(),
            json={"request_key": "anonymize-privacy-1"},
        )
        self.assertEqual(anonymized.json()["id"], repeat.json()["id"])

        blocked = self.client.post(
            "/api/privacy/delete",
            headers=self.headers(),
            json={"request_key": "delete-privacy-1", "confirmation_token": "wrong"},
        )
        self.assertEqual(422, blocked.status_code)
        deleted = self.client.post(
            "/api/privacy/delete",
            headers=self.headers(),
            json={"request_key": "delete-privacy-1", "confirmation_token": "DELETE"},
        )
        self.assertEqual(200, deleted.status_code, deleted.text)
        with Session(self.engine) as db:
            customer = db.get(Customer, self.customer_id)
            other = db.query(Customer).filter(Customer.business_id == self.other_business_id).one()
            self.assertEqual("deleted", customer.status)
            self.assertIsNone(customer.email)
            self.assertEqual("Other Tenant", other.name)
            logs = db.scalars(select(AuditLog).where(AuditLog.action == "privacy_delete")).all()
            self.assertTrue(logs)
            self.assertNotIn("Tin nhắn riêng", str(logs))


if __name__ == "__main__":
    unittest.main()
