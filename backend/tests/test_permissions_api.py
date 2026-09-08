import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models import Business, User
from app.models.audit_log import AuditLog


class PermissionsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Permissions", slug="permissions")
            db.add(business)
            db.flush()
            agent = User(business_id=business.id, full_name="Agent", email="agent@permissions.test", role="agent", is_active=True)
            db.add(agent)
            db.commit()
            cls.business_id = business.id
            cls.agent_id = agent.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_deny_override_is_visible_and_wins_for_agent(self):
        headers = {"X-Business-Id": str(self.business_id)}
        created = self.client.post(
            "/api/team/permissions",
            headers=headers,
            json={"resource": "orders", "action": "write", "effect": "deny", "role": "agent"},
        )
        self.assertEqual(201, created.status_code, created.text)
        listed = self.client.get("/api/team/permissions", headers=headers)
        self.assertEqual(1, listed.json()["total"])
        decision = self.client.get(
            f"/api/team/{self.agent_id}/permissions/effective",
            headers=headers,
        )
        self.assertEqual(200, decision.status_code, decision.text)
        item = next(item for item in decision.json()["items"] if item["resource"] == "orders" and item["action"] == "write")
        self.assertFalse(item["allowed"])

    def test_permission_override_is_audited_and_can_be_removed(self):
        headers = {"X-Business-Id": str(self.business_id)}
        created = self.client.post(
            "/api/team/permissions",
            headers=headers,
            json={"resource": "documents", "action": "write", "effect": "deny", "role": "agent"},
        )
        self.assertEqual(201, created.status_code, created.text)
        override_id = created.json()["id"]

        with Session(self.engine) as db:
            audit = db.query(AuditLog).filter(
                AuditLog.business_id == self.business_id,
                AuditLog.resource_type == "permission_override",
                AuditLog.resource_id == str(override_id),
                AuditLog.action == "create",
            ).first()
            self.assertIsNotNone(audit)

        removed = self.client.delete(f"/api/team/permissions/{override_id}", headers=headers)
        self.assertEqual(204, removed.status_code, removed.text)
        listed = self.client.get("/api/team/permissions", headers=headers)
        self.assertFalse(any(item["id"] == override_id for item in listed.json()["items"]))

        with Session(self.engine) as db:
            audit = db.query(AuditLog).filter(
                AuditLog.business_id == self.business_id,
                AuditLog.resource_type == "permission_override",
                AuditLog.resource_id == str(override_id),
                AuditLog.action == "delete",
            ).first()
            self.assertIsNotNone(audit)


if __name__ == "__main__":
    unittest.main()
