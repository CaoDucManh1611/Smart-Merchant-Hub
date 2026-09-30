import unittest
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.session import Base
from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.customer import Customer
from app.models.sales import Product


class P102OperationsHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Operations Hardening", slug="operations-hardening")
            db.add(business)
            db.flush()
            customer = Customer(
                business_id=business.id,
                channel="telegram",
                external_user_id="operations-customer",
                name="Operations Buyer",
            )
            db.add(customer)
            db.commit()
            cls.business_id = business.id
            cls.customer_id = customer.id

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

    def product(self, suffix: str, stock: int = 5):
        with Session(self.engine) as db:
            item = Product(
                business_id=self.business_id,
                sku=f"OPS-{suffix}",
                name=f"Operations {suffix}",
                price=Decimal("100"),
                stock_quantity=stock,
            )
            db.add(item)
            db.commit()
            return item.id

    def create_purchase(self, po_number: str, product_id: int, *, supplier_name: str = "Supplier"):
        response = self.client.post(
            "/api/purchase-orders",
            headers=self.headers(),
            json={
                "po_number": po_number,
                "supplier_name": supplier_name,
                "items": [{"product_id": product_id, "quantity": 2, "unit_cost": "50"}],
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def test_order_creation_rejects_non_draft_status(self):
        product_id = self.product("CREATE-STATUS")
        response = self.client.post(
            "/api/orders",
            headers=self.headers(),
            json={
                "customer_id": self.customer_id,
                "status": "confirmed",
                "items": [{"product_id": product_id, "quantity": 1}],
            },
        )
        self.assertEqual(422, response.status_code, response.text)

    def test_purchase_creation_rejects_non_draft_status(self):
        product_id = self.product("PO-CREATE-STATUS")
        response = self.client.post(
            "/api/purchase-orders",
            headers=self.headers(),
            json={
                "po_number": "PO-CREATE-STATUS",
                "supplier_name": "Supplier",
                "status": "submitted",
                "items": [{"product_id": product_id, "quantity": 1, "unit_cost": "50"}],
            },
        )
        self.assertEqual(422, response.status_code, response.text)

    def test_purchase_update_is_locked_after_submission(self):
        product_id = self.product("PO-LOCK")
        order = self.create_purchase("PO-LOCK", product_id)
        submitted = self.client.post(
            f"/api/purchase-orders/{order['id']}/transition",
            headers=self.headers(),
            json={"to_status": "submitted"},
        )
        self.assertEqual(200, submitted.status_code, submitted.text)
        response = self.client.patch(
            f"/api/purchase-orders/{order['id']}",
            headers=self.headers(),
            json={"notes": "Không được sửa sau khi gửi"},
        )
        self.assertEqual(409, response.status_code, response.text)

    def test_archived_supplier_cannot_be_used_for_new_purchase(self):
        product_id = self.product("ARCHIVED-SUPPLIER")
        supplier = self.client.post(
            "/api/suppliers",
            headers=self.headers(),
            json={"code": "SUP-ARCHIVED", "name": "Archived Supplier"},
        )
        self.assertEqual(201, supplier.status_code, supplier.text)
        supplier_id = supplier.json()["id"]
        archived = self.client.delete(f"/api/suppliers/{supplier_id}", headers=self.headers())
        self.assertEqual(204, archived.status_code, archived.text)
        response = self.client.post(
            "/api/purchase-orders",
            headers=self.headers(),
            json={
                "po_number": "PO-ARCHIVED-SUPPLIER",
                "supplier_id": supplier_id,
                "items": [{"product_id": product_id, "quantity": 1, "unit_cost": "50"}],
            },
        )
        self.assertEqual(409, response.status_code, response.text)

    def test_receipt_idempotency_key_cannot_be_reused_for_another_purchase(self):
        product_one = self.product("RECEIPT-KEY-1")
        product_two = self.product("RECEIPT-KEY-2")
        first = self.create_purchase("PO-RECEIPT-KEY-1", product_one)
        second = self.create_purchase("PO-RECEIPT-KEY-2", product_two)
        for order in (first, second):
            submitted = self.client.post(
                f"/api/purchase-orders/{order['id']}/transition",
                headers=self.headers(),
                json={"to_status": "submitted"},
            )
            self.assertEqual(200, submitted.status_code, submitted.text)
        payload = {
            "idempotency_key": "receipt-cross-po",
            "items": [{"purchase_order_item_id": first["items"][0]["id"], "quantity": 1}],
        }
        created = self.client.post(
            f"/api/purchase-orders/{first['id']}/receipts",
            headers=self.headers(),
            json=payload,
        )
        self.assertEqual(201, created.status_code, created.text)
        reused = self.client.post(
            f"/api/purchase-orders/{second['id']}/receipts",
            headers=self.headers(),
            json={
                "idempotency_key": "receipt-cross-po",
                "items": [{"purchase_order_item_id": second["items"][0]["id"], "quantity": 1}],
            },
        )
        self.assertEqual(409, reused.status_code, reused.text)

    def test_stock_change_uses_adjustment_endpoint_and_records_ledger(self):
        product_id = self.product("ADJUSTMENT")
        direct = self.client.patch(
            f"/api/products/{product_id}",
            headers=self.headers(),
            json={"stock_quantity": 7},
        )
        self.assertEqual(409, direct.status_code, direct.text)
        adjusted = self.client.post(
            f"/api/inventory/products/{product_id}/adjustments",
            headers=self.headers(),
            json={"quantity": 2, "reason": "Kiểm kê đầu ngày"},
        )
        self.assertEqual(201, adjusted.status_code, adjusted.text)
        self.assertEqual(7, adjusted.json()["balance"]["stock_quantity"])
        movements = self.client.get(
            f"/api/inventory/movements?product_id={product_id}",
            headers=self.headers(),
        )
        self.assertEqual(200, movements.status_code, movements.text)
        self.assertEqual("inventory_adjustment", movements.json()["items"][0]["movement_type"])

    def test_product_opening_stock_is_recorded_in_ledger(self):
        created = self.client.post(
            "/api/products",
            headers=self.headers(),
            json={"sku": "OPS-OPENING-STOCK", "name": "Opening Stock", "price": "100", "stock_quantity": 7},
        )
        self.assertEqual(201, created.status_code, created.text)
        product_id = created.json()["id"]
        movements = self.client.get(
            f"/api/inventory/movements?product_id={product_id}",
            headers=self.headers(),
        )
        self.assertEqual(200, movements.status_code, movements.text)
        self.assertEqual(1, movements.json()["total"])
        movement = movements.json()["items"][0]
        self.assertEqual("opening_balance", movement["movement_type"])
        self.assertEqual(7, movement["quantity"])
        self.assertEqual(0, movement["quantity_before"])
        self.assertEqual(7, movement["quantity_after"])

    def test_full_refund_endpoint_after_delivery_restores_stock_and_marks_order_refunded(self):
        product_id = self.product("REFUND-ENDPOINT")
        order = self.client.post(
            "/api/orders",
            headers=self.headers(),
            json={
                "order_number": "SO-REFUND-ENDPOINT",
                "customer_id": self.customer_id,
                "items": [{"product_id": product_id, "quantity": 1}],
            },
        ).json()
        for status in ("confirmed", "processing", "shipped", "delivered"):
            response = self.client.post(
                f"/api/orders/{order['id']}/transition",
                headers=self.headers(),
                json={"to_status": status},
            )
            self.assertEqual(200, response.status_code, response.text)
        paid = self.client.post(
            f"/api/orders/{order['id']}/payments",
            headers=self.headers(),
            json={
                "idempotency_key": "refund-endpoint-payment",
                "amount": "100",
                "method": "cash",
                "status": "paid",
            },
        )
        self.assertEqual(201, paid.status_code, paid.text)
        refunded = self.client.post(
            f"/api/orders/{order['id']}/refunds",
            headers=self.headers(),
            json={"idempotency_key": "refund-endpoint-full", "amount": "100", "reason": "Khách trả hàng"},
        )
        self.assertEqual(201, refunded.status_code, refunded.text)
        self.assertEqual("refunded", refunded.json()["order"]["status"])
        balance = self.client.get(
            f"/api/inventory/products/{product_id}",
            headers=self.headers(),
        )
        self.assertEqual(5, balance.json()["stock_quantity"])

    def test_purchase_payment_is_partial_idempotent_and_bounded(self):
        product_id = self.product("PO-PAYMENT")
        order = self.create_purchase("PO-PAYMENT", product_id)
        first = self.client.post(
            f"/api/purchase-orders/{order['id']}/payments",
            headers=self.headers(),
            json={"idempotency_key": "po-payment-1", "amount": "50", "method": "bank_transfer", "status": "paid"},
        )
        self.assertEqual(201, first.status_code, first.text)
        self.assertEqual("partial", first.json()["order"]["payment_status"])
        duplicate = self.client.post(
            f"/api/purchase-orders/{order['id']}/payments",
            headers=self.headers(),
            json={"idempotency_key": "po-payment-1", "amount": "50", "method": "bank_transfer", "status": "paid"},
        )
        self.assertEqual(200, duplicate.status_code, duplicate.text)
        self.assertEqual(first.json()["payment"]["id"], duplicate.json()["payment"]["id"])
        overpay = self.client.post(
            f"/api/purchase-orders/{order['id']}/payments",
            headers=self.headers(),
            json={"idempotency_key": "po-payment-over", "amount": "51", "method": "cash", "status": "paid"},
        )
        self.assertEqual(409, overpay.status_code, overpay.text)
        complete = self.client.post(
            f"/api/purchase-orders/{order['id']}/payments",
            headers=self.headers(),
            json={"idempotency_key": "po-payment-2", "amount": "50", "method": "cash", "status": "paid"},
        )
        self.assertEqual(201, complete.status_code, complete.text)
        self.assertEqual("paid", complete.json()["order"]["payment_status"])


if __name__ == "__main__":
    unittest.main()
