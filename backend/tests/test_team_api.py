import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models import Business, User


class TeamApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="Team One", slug="team-one")
            two = Business(name="Team Two", slug="team-two")
            db.add_all([one, two])
            db.flush()
            db.add(User(business_id=one.id, full_name="Owner", email="owner@example.test", role="owner"))
            db.commit()
            cls.business_one = one.id
            cls.business_two = two.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_team_list_is_tenant_scoped(self):
        response = self.client.get("/api/team", headers={"X-Business-Id": str(self.business_one)})
        self.assertEqual(200, response.status_code)
        self.assertGreaterEqual(response.json()["total"], 1)
        self.assertIn("Owner", [item["full_name"] for item in response.json()["items"]])

        other = self.client.get("/api/team", headers={"X-Business-Id": str(self.business_two)})
        self.assertEqual([], other.json()["items"])

    def test_create_and_update_team_member(self):
        created = self.client.post(
            "/api/team",
            headers={"X-Business-Id": str(self.business_one)},
            json={"full_name": "Support Agent", "email": "AGENT@example.test", "role": "agent"},
        )
        self.assertEqual(201, created.status_code)
        body = created.json()
        self.assertEqual("agent@example.test", body["email"])
        self.assertTrue(body["is_active"])

        updated = self.client.patch(
            f"/api/team/{body['id']}",
            headers={"X-Business-Id": str(self.business_one)},
            json={"role": "viewer", "is_active": False},
        )
        self.assertEqual(200, updated.status_code)
        self.assertEqual("viewer", updated.json()["role"])
        self.assertFalse(updated.json()["is_active"])

    def test_duplicate_email_and_cross_tenant_resource_are_rejected(self):
        duplicate = self.client.post(
            "/api/team",
            headers={"X-Business-Id": str(self.business_one)},
            json={"full_name": "Duplicate", "email": "OWNER@example.test", "role": "agent"},
        )
        self.assertEqual(409, duplicate.status_code)

        member = self.client.get("/api/team", headers={"X-Business-Id": str(self.business_one)}).json()["items"][0]
        cross_tenant = self.client.get(
            f"/api/team/{member['id']}",
            headers={"X-Business-Id": str(self.business_two)},
        )
        self.assertEqual(404, cross_tenant.status_code)

    def test_invalid_role_is_rejected(self):
        response = self.client.post(
            "/api/team",
            headers={"X-Business-Id": str(self.business_one)},
            json={"full_name": "Unknown", "email": "unknown@example.test", "role": "superuser"},
        )
        self.assertEqual(422, response.status_code)


if __name__ == "__main__":
    unittest.main()
