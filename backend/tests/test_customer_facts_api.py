import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.customer import Customer


class CustomerFactsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="Facts One", slug="facts-one")
            two = Business(name="Facts Two", slug="facts-two")
            db.add_all([one, two])
            db.flush()
            customer = Customer(
                business_id=one.id,
                channel="telegram",
                external_user_id="facts-user",
                name="Facts Buyer",
            )
            other = Customer(
                business_id=two.id,
                channel="telegram",
                external_user_id="other-facts-user",
            )
            db.add_all([customer, other])
            db.commit()
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

    def test_customer_fact_crud_and_profile_projection(self):
        created = self.client.post(
            f"/api/customers/{self.customer_id}/facts",
            headers={"X-Business-Id": "1"},
            json={
                "fact_type": "preference",
                "fact_key": "interested_category",
                "fact_value": "serum",
                "confidence": 0.93,
                "source_type": "message",
                "is_verified": True,
            },
        )
        self.assertEqual(201, created.status_code, created.text)
        fact = created.json()
        self.assertEqual("serum", fact["fact_value"])
        self.assertTrue(fact["is_verified"])

        listed = self.client.get(
            f"/api/customers/{self.customer_id}/facts?verified=true",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, listed.status_code)
        self.assertEqual([fact["id"]], [item["id"] for item in listed.json()["items"]])

        profile = self.client.get(
            f"/api/customers/{self.customer_id}",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(["interested_category"], [item["fact_key"] for item in profile.json()["facts"]])

        updated = self.client.patch(
            f"/api/customers/{self.customer_id}/facts/{fact['id']}",
            headers={"X-Business-Id": "1"},
            json={"fact_value": "skincare", "confidence": 0.97},
        )
        self.assertEqual(200, updated.status_code, updated.text)
        self.assertEqual("skincare", updated.json()["fact_value"])

        removed = self.client.delete(
            f"/api/customers/{self.customer_id}/facts/{fact['id']}",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(204, removed.status_code)

    def test_cross_tenant_customer_fact_is_rejected(self):
        response = self.client.post(
            f"/api/customers/{self.other_customer_id}/facts",
            headers={"X-Business-Id": "1"},
            json={
                "fact_type": "preference",
                "fact_key": "budget_max",
                "fact_value": 500000,
            },
        )
        self.assertEqual(404, response.status_code)

        hidden = self.client.get(
            f"/api/customers/{self.other_customer_id}/facts",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(404, hidden.status_code)

    def test_fact_source_must_belong_to_same_customer_and_business(self):
        response = self.client.post(
            f"/api/customers/{self.customer_id}/facts",
            headers={"X-Business-Id": "1"},
            json={
                "fact_type": "preference",
                "fact_key": "last_order",
                "fact_value": "wrong-source",
                "source_type": "message",
                "source_message_id": 999999,
            },
        )
        self.assertEqual(422, response.status_code)

    def test_fact_extraction_status_is_tenant_owned_and_toggleable(self):
        initial = self.client.get(
            "/api/customers/fact-extraction-status",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, initial.status_code)
        self.assertFalse(initial.json()["enabled"])

        enabled = self.client.post(
            "/api/customers/fact-extraction-status",
            headers={"X-Business-Id": "1"},
            json={"enabled": True},
        )
        self.assertEqual(200, enabled.status_code)
        self.assertTrue(enabled.json()["enabled"])

        other = self.client.get(
            "/api/customers/fact-extraction-status",
            headers={"X-Business-Id": "2"},
        )
        self.assertEqual(200, other.status_code)
        self.assertFalse(other.json()["enabled"])


if __name__ == "__main__":
    unittest.main()
