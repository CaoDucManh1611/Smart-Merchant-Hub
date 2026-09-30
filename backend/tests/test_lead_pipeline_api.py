import unittest
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models import Business, Conversation, Customer, Lead


class LeadPipelineApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="Pipeline One", slug="pipeline-one")
            two = Business(name="Pipeline Two", slug="pipeline-two")
            db.add_all([one, two])
            db.flush()
            customer = Customer(business_id=one.id, channel="telegram", external_user_id="lead-a", name="Buyer A")
            other_customer = Customer(business_id=two.id, channel="facebook", external_user_id="lead-b", name="Buyer B")
            db.add_all([customer, other_customer])
            db.flush()
            conversation = Conversation(business_id=one.id, customer_id=customer.id, channel="telegram")
            db.add(conversation)
            db.commit()
            cls.customer_id = customer.id
            cls.other_customer_id = other_customer.id
            cls.conversation_id = conversation.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_create_and_list_lead_is_tenant_scoped(self):
        response = self.client.post(
            "/api/leads",
            headers={"X-Business-Id": "1"},
            json={
                "title": "Serum follow-up",
                "customer_id": self.customer_id,
                "conversation_id": self.conversation_id,
                "stage": "qualified",
                "value": 840000,
                "probability": 70,
            },
        )
        self.assertEqual(201, response.status_code)
        body = response.json()
        self.assertEqual("qualified", body["stage"])
        self.assertEqual("telegram", body["source_channel"])
        self.assertEqual("840000.00", body["value"])

        own = self.client.get("/api/leads", headers={"X-Business-Id": "1"})
        self.assertEqual(200, own.status_code)
        self.assertEqual(1, own.json()["total"])
        other = self.client.get("/api/leads", headers={"X-Business-Id": "2"})
        self.assertEqual(200, other.status_code)
        self.assertEqual([], other.json()["items"])

    def test_lead_rejects_cross_tenant_customer(self):
        response = self.client.post(
            "/api/leads",
            headers={"X-Business-Id": "1"},
            json={"title": "Invalid", "customer_id": self.other_customer_id},
        )
        self.assertEqual(404, response.status_code)

    def test_pipeline_summary_groups_value_by_stage(self):
        response = self.client.get("/api/reports/pipeline", headers={"X-Business-Id": "1"})
        self.assertEqual(200, response.status_code)
        body = response.json()
        qualified = next(item for item in body["items"] if item["stage"] == "qualified")
        self.assertEqual(1, qualified["lead_count"])
        self.assertEqual("840000.00", qualified["value"])
        self.assertEqual("840000.00", body["total_value"])


if __name__ == "__main__":
    unittest.main()
