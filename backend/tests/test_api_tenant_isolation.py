import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.message import Message


class ApiTenantIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="One", slug="one")
            two = Business(name="Two", slug="two")
            db.add_all([one, two])
            db.flush()
            customer = Customer(business_id=two.id, channel="facebook", external_user_id="u2")
            db.add(customer)
            db.flush()
            cls.other_tenant_conversation_id = Conversation(
                business_id=two.id,
                customer_id=customer.id,
                channel="facebook",
                status="open",
            )
            db.add(cls.other_tenant_conversation_id)
            db.commit()
            cls.other_tenant_conversation_id = cls.other_tenant_conversation_id.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_tenant_a_cannot_read_tenant_b_conversation(self):
        response = self.client.get(
            f"/api/conversations/{self.other_tenant_conversation_id}/messages",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(404, response.status_code)

    def test_conversation_list_contains_only_requested_tenant(self):
        response = self.client.get(
            "/api/conversations",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual([], response.json()["items"])


if __name__ == "__main__":
    unittest.main()
