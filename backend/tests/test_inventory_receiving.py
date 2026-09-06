import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.session import Base
from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.sales import Product


class InventoryReceivingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Inventory One", slug="inventory-one")
            db.add(business)
            db.flush()
            product = Product(
                business_id=business.id,
                sku="INV-01",
                name="Inventory Product",
                price=10,
                stock_quantity=0,
            )
            db.add(product)
            db.commit()
            cls.business_id = business.id
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

    def create_submitted_po(self, po_number: str, quantity: int = 5):
        created = self.client.post(
            "/api/purchase-orders",
            headers=self.headers(),
            json={
                "po_number": po_number,
                "supplier_name": "Inventory Supplier",
                "items": [{"product_id": self.product_id, "quantity": quantity, "unit_cost": "8"}],
            },
        )
        self.assertEqual(201, created.status_code, created.text)
        order = created.json()
        submitted = self.client.post(
            f"/api/purchase-orders/{order['id']}/transition",
            headers=self.headers(),
            json={"to_status": "submitted"},
        )
        self.assertEqual(200, submitted.status_code, submitted.text)
        return submitted.json()

    def test_partial_receipt_increases_stock_and_updates_po(self):
        order = self.create_submitted_po("PO-RECEIVE-1")
        item_id = order["items"][0]["id"]
        response = self.client.post(
            f"/api/purchase-orders/{order['id']}/receipts",
            headers=self.headers(),
            json={
                "idempotency_key": "receipt-1",
                "items": [{"purchase_order_item_id": item_id, "quantity": 2}],
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        self.assertEqual("partially_received", response.json()["purchase_order"]["status"])
        self.assertEqual(2, response.json()["purchase_order"]["items"][0]["received_quantity"])

        inventory = self.client.get(
            f"/api/inventory/products/{self.product_id}",
            headers=self.headers(),
        )
        self.assertEqual(200, inventory.status_code)
        self.assertEqual(2, inventory.json()["stock_quantity"])
        self.assertEqual(2, inventory.json()["available_quantity"])

    def test_receipt_cannot_exceed_ordered_quantity(self):
        order = self.create_submitted_po("PO-RECEIVE-OVER", quantity=3)
        response = self.client.post(
            f"/api/purchase-orders/{order['id']}/receipts",
            headers=self.headers(),
            json={
                "idempotency_key": "receipt-over",
                "items": [{"purchase_order_item_id": order["items"][0]["id"], "quantity": 4}],
            },
        )
        self.assertEqual(409, response.status_code)

    def test_receipt_idempotency_does_not_duplicate_stock(self):
        order = self.create_submitted_po("PO-RECEIVE-IDEMP", quantity=3)
        payload = {
            "idempotency_key": "receipt-same",
            "items": [{"purchase_order_item_id": order["items"][0]["id"], "quantity": 1}],
        }
        first = self.client.post(
            f"/api/purchase-orders/{order['id']}/receipts",
            headers=self.headers(),
            json=payload,
        )
        second = self.client.post(
            f"/api/purchase-orders/{order['id']}/receipts",
            headers=self.headers(),
            json=payload,
        )
        self.assertEqual(201, first.status_code, first.text)
        self.assertEqual(200, second.status_code, second.text)
        self.assertEqual(first.json()["id"], second.json()["id"])


if __name__ == "__main__":
    unittest.main()
