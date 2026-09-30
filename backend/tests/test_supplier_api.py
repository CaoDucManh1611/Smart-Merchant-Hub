import unittest
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.database.session import Base
from app.models.business import Business
from app.models.sales import Product


class SupplierApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="Supplier One", slug="supplier-one")
            two = Business(name="Supplier Two", slug="supplier-two")
            db.add_all([one, two])
            db.flush()
            product = Product(business_id=one.id, sku="SUP-PROD", name="Product", price=Decimal("10"))
            db.add(product)
            db.commit()
            cls.business_id = one.id
            cls.other_business_id = two.id
            cls.product_id = product.id

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

    def test_supplier_crud_is_tenant_scoped(self):
        created = self.client.post(
            "/api/suppliers",
            headers=self.headers(),
            json={"code": "SUP-01", "name": "Nhà cung cấp 1", "phone": "0901"},
        )
        self.assertEqual(201, created.status_code)
        supplier_id = created.json()["id"]
        self.assertEqual(
            404,
            self.client.get(f"/api/suppliers/{supplier_id}", headers=self.headers(self.other_business_id)).status_code,
        )
        listed = self.client.get("/api/suppliers", headers=self.headers())
        self.assertGreaterEqual(listed.json()["total"], 1)
        archived = self.client.delete(f"/api/suppliers/{supplier_id}", headers=self.headers())
        self.assertEqual(204, archived.status_code)
        self.assertEqual("archived", self.client.get(f"/api/suppliers/{supplier_id}", headers=self.headers()).json()["status"])

    def test_duplicate_supplier_code_is_rejected(self):
        payload = {"code": "SUP-DUP", "name": "NCC"}
        self.assertEqual(201, self.client.post("/api/suppliers", headers=self.headers(), json=payload).status_code)
        self.assertEqual(409, self.client.post("/api/suppliers", headers=self.headers(), json=payload).status_code)

    def test_purchase_order_persists_supplier_and_product_snapshots(self):
        supplier = self.client.post(
            "/api/suppliers",
            headers=self.headers(),
            json={"code": "SUP-SNAPSHOT", "name": "Supplier Snapshot"},
        ).json()
        response = self.client.post(
            "/api/purchase-orders",
            headers=self.headers(),
            json={
                "po_number": "PO-SNAP-1",
                "supplier_id": supplier["id"],
                "items": [{"product_id": self.product_id, "quantity": 2, "unit_cost": "12.50"}],
            },
        )
        self.assertEqual(201, response.status_code)
        body = response.json()
        self.assertEqual(supplier["id"], body["supplier_id"])
        self.assertEqual("Supplier Snapshot", body["supplier_name"])
        self.assertEqual("Product", body["items"][0]["product_name"])

    def test_foreign_supplier_is_rejected(self):
        response = self.client.post(
            "/api/purchase-orders",
            headers=self.headers(),
            json={
                "po_number": "PO-FOREIGN-SUP",
                "supplier_id": 99999,
                "items": [{"product_id": self.product_id, "quantity": 1, "unit_cost": "10"}],
            },
        )
        self.assertEqual(404, response.status_code)

    def test_archived_supplier_cannot_be_used_for_new_or_updated_purchase_order(self):
        supplier = self.client.post(
            "/api/suppliers",
            headers=self.headers(),
            json={"code": "SUP-ARCHIVED", "name": "Archived supplier"},
        ).json()
        self.assertEqual(
            204,
            self.client.delete(f"/api/suppliers/{supplier['id']}", headers=self.headers()).status_code,
        )

        created = self.client.post(
            "/api/purchase-orders",
            headers=self.headers(),
            json={
                "po_number": "PO-ARCHIVED-SUPPLIER",
                "supplier_id": supplier["id"],
                "items": [{"product_id": self.product_id, "quantity": 1, "unit_cost": "10"}],
            },
        )
        self.assertEqual(409, created.status_code, created.text)

        manual_supplier_order = self.client.post(
            "/api/purchase-orders",
            headers=self.headers(),
            json={
                "po_number": "PO-UPDATE-ARCHIVED-SUPPLIER",
                "supplier_name": "Manual supplier",
                "items": [{"product_id": self.product_id, "quantity": 1, "unit_cost": "10"}],
            },
        )
        self.assertEqual(201, manual_supplier_order.status_code, manual_supplier_order.text)
        updated = self.client.patch(
            f"/api/purchase-orders/{manual_supplier_order.json()['id']}",
            headers=self.headers(),
            json={"supplier_id": supplier["id"]},
        )
        self.assertEqual(409, updated.status_code, updated.text)

    def test_purchase_order_supplier_is_frozen_after_submission(self):
        supplier = self.client.post(
            "/api/suppliers",
            headers=self.headers(),
            json={"code": "SUP-FROZEN", "name": "Frozen supplier"},
        ).json()
        purchase = self.client.post(
            "/api/purchase-orders",
            headers=self.headers(),
            json={
                "po_number": "PO-FROZEN-SUPPLIER",
                "supplier_name": "Original supplier",
                "items": [{"product_id": self.product_id, "quantity": 1, "unit_cost": "10"}],
            },
        )
        self.assertEqual(201, purchase.status_code, purchase.text)
        self.assertEqual(
            200,
            self.client.post(
                f"/api/purchase-orders/{purchase.json()['id']}/transition",
                headers=self.headers(),
                json={"to_status": "submitted"},
            ).status_code,
        )
        update = self.client.patch(
            f"/api/purchase-orders/{purchase.json()['id']}",
            headers=self.headers(),
            json={"supplier_id": supplier["id"]},
        )
        self.assertEqual(409, update.status_code, update.text)


if __name__ == "__main__":
    unittest.main()
