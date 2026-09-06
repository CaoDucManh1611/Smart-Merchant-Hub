import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.customer import Customer
from app.models.sales import Product


class P102TimelineReportsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Timeline Reports", slug="timeline-reports")
            db.add(business)
            db.flush()
            customer = Customer(
                business_id=business.id,
                channel="telegram",
                external_user_id="timeline-customer",
                name="Timeline Buyer",
            )
            product = Product(
                business_id=business.id,
                sku="TIMELINE-01",
                name="Timeline Product",
                price=100,
                stock_quantity=5,
            )
            db.add_all([customer, product])
            db.commit()
            cls.business_id = business.id
            cls.customer_id = customer.id
            cls.product_id = product.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def headers(self):
        return {"X-Business-Id": str(self.business_id)}

    def test_timeline_includes_sales_payment_event_but_not_unlinked_purchase(self):
        order = self.client.post(
            "/api/orders",
            headers=self.headers(),
            json={
                "order_number": "SO-TIMELINE-1",
                "customer_id": self.customer_id,
                "items": [{"product_id": self.product_id, "quantity": 1}],
            },
        ).json()
        payment = self.client.post(
            f"/api/orders/{order['id']}/payments",
            headers=self.headers(),
            json={"idempotency_key": "timeline-pay-1", "amount": "100", "method": "cash", "status": "paid"},
        )
        self.assertEqual(201, payment.status_code, payment.text)
        purchase = self.client.post(
            "/api/purchase-orders",
            headers=self.headers(),
            json={
                "po_number": "PO-TIMELINE-1",
                "supplier_name": "Supplier",
                "items": [{"product_id": self.product_id, "quantity": 1, "unit_cost": "50"}],
            },
        )
        self.assertEqual(201, purchase.status_code, purchase.text)

        timeline = self.client.get(f"/api/customers/{self.customer_id}/timeline", headers=self.headers()).json()
        event_types = {item["event_type"] for item in timeline["items"]}
        self.assertIn("sales_order", event_types)
        self.assertIn("order_payment", event_types)
        self.assertNotIn("purchase_order", event_types)

    def test_inventory_report_is_tenant_scoped_and_has_availability(self):
        response = self.client.get("/api/reports/inventory", headers=self.headers())
        self.assertEqual(200, response.status_code, response.text)
        self.assertIn("items", response.json())
        item = next(row for row in response.json()["items"] if row["product_id"] == self.product_id)
        self.assertEqual(5, item["stock_quantity"])
        self.assertEqual(0, item["reserved_quantity"])
        self.assertEqual(5, item["available_quantity"])

    def test_purchase_cost_report_has_supplier_and_received_cost_shape(self):
        response = self.client.get("/api/reports/purchase-costs", headers=self.headers())
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertIn("items", body)
        self.assertIn("total_received_cost", body)


if __name__ == "__main__":
    unittest.main()
