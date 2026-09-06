import unittest
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.sales import Product


class ProductOrderApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="Sales One", slug="sales-one")
            two = Business(name="Sales Two", slug="sales-two")
            db.add_all([one, two])
            db.flush()
            customer = Customer(
                business_id=one.id,
                channel="telegram",
                external_user_id="sales-customer",
                name="Buyer One",
            )
            other_customer = Customer(
                business_id=two.id,
                channel="facebook",
                external_user_id="sales-customer-b",
            )
            db.add_all([customer, other_customer])
            db.flush()
            conversation = Conversation(
                business_id=one.id,
                customer_id=customer.id,
                channel="telegram",
            )
            product = Product(
                business_id=one.id,
                sku="SERUM-01",
                name="Serum C",
                price=Decimal("420000"),
                stock_quantity=10,
            )
            other_product = Product(
                business_id=two.id,
                sku="OTHER-01",
                name="Other product",
                price=Decimal("100"),
                stock_quantity=10,
            )
            db.add_all([conversation, product, other_product])
            db.commit()
            cls.customer_id = customer.id
            cls.other_customer_id = other_customer.id
            cls.conversation_id = conversation.id
            cls.product_id = product.id
            cls.other_product_id = other_product.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_product_list_is_tenant_scoped(self):
        response = self.client.get("/api/products", headers={"X-Business-Id": "1"})
        self.assertEqual(200, response.status_code)
        product_ids = [item["id"] for item in response.json()["items"]]
        self.assertIn(self.product_id, product_ids)
        self.assertNotIn(self.other_product_id, product_ids)

    def test_order_uses_database_product_price_and_calculates_total(self):
        response = self.client.post(
            "/api/orders",
            headers={"X-Business-Id": "1"},
            json={
                "order_number": "ORD-001",
                "customer_id": self.customer_id,
                "conversation_id": self.conversation_id,
                "items": [{"product_id": self.product_id, "quantity": 2}],
            },
        )
        self.assertEqual(201, response.status_code)
        body = response.json()
        self.assertEqual("840000.00", body["total_amount"])
        self.assertEqual(1, len(body["items"]))
        self.assertEqual("420000.00", body["items"][0]["unit_price"])

    def test_order_number_is_generated_when_omitted(self):
        response = self.client.post(
            "/api/orders",
            headers={"X-Business-Id": "1"},
            json={
                "customer_id": self.customer_id,
                "items": [{"product_id": self.product_id, "quantity": 1}],
            },
        )
        self.assertEqual(201, response.status_code)
        self.assertRegex(response.json()["order_number"], r"^ORD-\d{14}(?:-\d+)?$")

    def test_order_cannot_reference_other_tenant_product(self):
        response = self.client.post(
            "/api/orders",
            headers={"X-Business-Id": "1"},
            json={
                "order_number": "ORD-CROSS-TENANT",
                "customer_id": self.customer_id,
                "items": [{"product_id": self.other_product_id, "quantity": 1}],
            },
        )
        self.assertEqual(404, response.status_code)

    def test_order_cannot_reference_other_tenant_customer(self):
        response = self.client.post(
            "/api/orders",
            headers={"X-Business-Id": "1"},
            json={
                "order_number": "ORD-CROSS-CUSTOMER",
                "customer_id": self.other_customer_id,
                "items": [{"product_id": self.product_id, "quantity": 1}],
            },
        )
        self.assertEqual(404, response.status_code)

    def test_order_must_start_as_draft(self):
        response = self.client.post(
            "/api/orders",
            headers={"X-Business-Id": "1"},
            json={
                "order_number": "ORD-NON-DRAFT",
                "customer_id": self.customer_id,
                "items": [{"product_id": self.product_id, "quantity": 1}],
                "status": "confirmed",
            },
        )
        self.assertEqual(422, response.status_code, response.text)

    def test_stock_adjustment_is_ledgered_and_product_patch_cannot_bypass_it(self):
        bypass = self.client.patch(
            f"/api/products/{self.product_id}",
            headers={"X-Business-Id": "1"},
            json={"stock_quantity": 20},
        )
        self.assertEqual(409, bypass.status_code, bypass.text)

        adjustment = self.client.post(
            f"/api/inventory/products/{self.product_id}/adjustments",
            headers={"X-Business-Id": "1"},
            json={"quantity": 2, "note": "Kiểm kho"},
        )
        self.assertEqual(201, adjustment.status_code, adjustment.text)
        self.assertEqual(12, adjustment.json()["balance"]["stock_quantity"])

        movements = self.client.get(
            f"/api/inventory/movements?product_id={self.product_id}",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(1, movements.json()["total"])
        self.assertEqual("inventory_adjustment", movements.json()["items"][0]["movement_type"])
        self.assertEqual(2, movements.json()["items"][0]["quantity"])

        zero_adjustment = self.client.post(
            f"/api/inventory/products/{self.product_id}/adjustments",
            headers={"X-Business-Id": "1"},
            json={"quantity": 0},
        )
        self.assertEqual(422, zero_adjustment.status_code, zero_adjustment.text)

    def test_product_creation_records_opening_stock_in_inventory_ledger(self):
        created = self.client.post(
            "/api/products",
            headers={"X-Business-Id": "1"},
            json={
                "sku": "OPENING-STOCK",
                "name": "Opening stock product",
                "price": "10",
                "stock_quantity": 3,
            },
        )
        self.assertEqual(201, created.status_code, created.text)
        product_id = created.json()["id"]

        movements = self.client.get(
            f"/api/inventory/movements?product_id={product_id}",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(1, movements.json()["total"])
        movement = movements.json()["items"][0]
        self.assertEqual("opening_balance", movement["movement_type"])
        self.assertEqual(3, movement["quantity"])
        self.assertEqual(0, movement["quantity_before"])
        self.assertEqual(3, movement["quantity_after"])

    def test_inventory_movements_rejects_a_product_from_another_tenant(self):
        response = self.client.get(
            f"/api/inventory/movements?product_id={self.other_product_id}",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(404, response.status_code, response.text)

    def test_revenue_report_is_grouped_by_conversation_channel_and_tenant_scoped(self):
        existing = self.client.get(
            "/api/orders",
            headers={"X-Business-Id": "1"},
        )
        if not existing.json()["items"]:
            create = self.client.post(
                "/api/orders",
                headers={"X-Business-Id": "1"},
                json={
                    "order_number": "ORD-REPORT",
                    "customer_id": self.customer_id,
                    "conversation_id": self.conversation_id,
                    "items": [{"product_id": self.product_id, "quantity": 2}],
                },
            )
            self.assertEqual(201, create.status_code)
        response = self.client.get(
            "/api/reports/revenue-by-channel",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, response.status_code)
        body = response.json()
        telegram = next(item for item in body["items"] if item["channel"] == "telegram")
        self.assertGreaterEqual(float(body["total_revenue"]), 840000)
        self.assertGreaterEqual(telegram["order_count"], 1)
        self.assertGreaterEqual(float(telegram["revenue"]), 840000)

        other_tenant = self.client.get(
            "/api/reports/revenue-by-channel",
            headers={"X-Business-Id": "2"},
        )
        self.assertEqual(200, other_tenant.status_code)
        self.assertEqual([], other_tenant.json()["items"])
        self.assertEqual(0, float(other_tenant.json()["total_revenue"]))


if __name__ == "__main__":
    unittest.main()
