import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.customer import Customer
from app.models.sales import Order


class OrderLogisticsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            first = Business(name="Logistics One", slug="logistics-one")
            second = Business(name="Logistics Two", slug="logistics-two")
            db.add_all([first, second])
            db.flush()
            customer = Customer(business_id=first.id, channel="telegram", external_user_id="logistics-customer")
            other_customer = Customer(business_id=second.id, channel="telegram", external_user_id="other-customer")
            db.add_all([customer, other_customer])
            db.flush()
            order = Order(business_id=first.id, customer_id=customer.id, order_number="LOG-1", status="processing", total_amount=10)
            other_order = Order(business_id=second.id, customer_id=other_customer.id, order_number="LOG-2", status="processing", total_amount=10)
            db.add_all([order, other_order])
            db.commit()
            cls.business_id = first.id
            cls.other_business_id = second.id
            cls.order_id = order.id
            cls.other_order_id = other_order.id

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

    def test_updates_logistics_metadata_and_appends_order_event(self):
        response = self.client.patch(
            f"/api/orders/{self.order_id}/logistics",
            headers=self.headers(),
            json={"shipping_provider": "ghn", "tracking_code": "GHN-123", "shipping_status": "in_transit"},
        )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("ghn", response.json()["shipping_provider"])
        self.assertEqual("GHN-123", response.json()["tracking_code"])
        self.assertEqual("in_transit", response.json()["shipping_status"])

        events = self.client.get(f"/api/orders/{self.order_id}/events", headers=self.headers())
        self.assertEqual(200, events.status_code)
        self.assertTrue(any(item["event_type"] == "logistics_updated" for item in events.json()["items"]))

    def test_logistics_update_is_tenant_scoped_and_status_is_validated(self):
        hidden = self.client.patch(
            f"/api/orders/{self.other_order_id}/logistics",
            headers=self.headers(),
            json={"shipping_status": "delivered"},
        )
        self.assertEqual(404, hidden.status_code)

        invalid = self.client.patch(
            f"/api/orders/{self.order_id}/logistics",
            headers=self.headers(),
            json={"shipping_status": "flying"},
        )
        self.assertEqual(422, invalid.status_code)


if __name__ == "__main__":
    unittest.main()
