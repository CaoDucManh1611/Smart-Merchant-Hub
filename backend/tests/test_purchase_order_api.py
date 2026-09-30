import unittest
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.customer import Customer
from app.models.sales import Product


class PurchaseOrderApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="PO One", slug="po-one")
            two = Business(name="PO Two", slug="po-two")
            db.add_all([one, two])
            db.flush()
            product = Product(business_id=one.id, sku="PO-SKU", name="Bot plan", price=100)
            foreign_product = Product(business_id=two.id, sku="PO-SKU-2", name="Other", price=50)
            db.add_all([product, foreign_product])
            db.commit()
            cls.business_id = one.id
            cls.other_business_id = two.id
            cls.product_id = product.id
            cls.foreign_product_id = foreign_product.id

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

    def test_create_purchase_order_calculates_total_and_lists(self):
        response = self.client.post(
            "/api/purchase-orders",
            headers=self.headers(),
            json={
                "po_number": "PO-001",
                "supplier_name": "Smart Merchant Hub",
                "items": [{"product_id": self.product_id, "quantity": 2, "unit_cost": "125000"}],
                "status": "draft",
                "notes": "Gói chatbot tháng 9",
            },
        )
        self.assertEqual(201, response.status_code)
        body = response.json()
        self.assertEqual("250000.00", body["total_spend"])
        self.assertEqual("draft", body["status"])
        self.assertEqual(1, len(body["items"]))

        listed = self.client.get("/api/purchase-orders", headers=self.headers())
        self.assertEqual(1, listed.json()["total"])

    def test_foreign_product_is_rejected(self):
        response = self.client.post(
            "/api/purchase-orders",
            headers=self.headers(),
            json={
                "po_number": "PO-FOREIGN",
                "supplier_name": "NCC khác",
                "items": [{"product_id": self.foreign_product_id, "quantity": 1, "unit_cost": 10}],
            },
        )
        self.assertEqual(404, response.status_code)

    def test_purchase_order_lifecycle_rejects_invalid_jump(self):
        created = self.client.post(
            "/api/purchase-orders",
            headers=self.headers(),
            json={
                "po_number": "PO-LIFE",
                "supplier_name": "NCC",
                "items": [{"product_id": self.product_id, "quantity": 1, "unit_cost": 10}],
            },
        )
        po_id = created.json()["id"]
        invalid = self.client.post(
            f"/api/purchase-orders/{po_id}/transition",
            headers=self.headers(),
            json={"to_status": "received"},
        )
        self.assertEqual(409, invalid.status_code)
        valid = self.client.post(
            f"/api/purchase-orders/{po_id}/transition",
            headers=self.headers(),
            json={"to_status": "submitted"},
        )
        self.assertEqual(200, valid.status_code)
        self.assertEqual("submitted", valid.json()["status"])

    def test_purchase_order_must_start_as_draft(self):
        response = self.client.post(
            "/api/purchase-orders",
            headers=self.headers(),
            json={
                "po_number": "PO-NON-DRAFT",
                "supplier_name": "NCC",
                "items": [{"product_id": self.product_id, "quantity": 1, "unit_cost": 10}],
                "status": "submitted",
            },
        )
        self.assertEqual(422, response.status_code, response.text)


if __name__ == "__main__":
    unittest.main()
