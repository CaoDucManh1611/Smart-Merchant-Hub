import unittest

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


class SalesInventoryLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Sales Inventory", slug="sales-inventory")
            db.add(business)
            db.flush()
            customer = Customer(
                business_id=business.id,
                channel="telegram",
                external_user_id="sales-inventory-customer",
                name="Inventory Buyer",
            )
            product = Product(
                business_id=business.id,
                sku="SALE-INV-01",
                name="Sale Inventory Product",
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

    def setUp(self):
        # Each scenario starts from the same inventory snapshot.  The
        # lifecycle tests intentionally exercise stock mutations, so they
        # must not leak state into one another through StaticPool.
        with Session(self.engine) as db:
            product = db.get(Product, self.product_id)
            product.stock_quantity = 5
            product.reserved_quantity = 0
            db.commit()

    def create_order(self, order_number: str, quantity: int):
        response = self.client.post(
            "/api/orders",
            headers=self.headers(),
            json={
                "order_number": order_number,
                "customer_id": self.customer_id,
                "items": [{"product_id": self.product_id, "quantity": quantity}],
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def test_confirm_reserves_and_ship_decrements_stock(self):
        order = self.create_order("SO-INVENTORY-1", 2)
        confirmed = self.client.post(
            f"/api/orders/{order['id']}/transition",
            headers=self.headers(),
            json={"to_status": "confirmed"},
        )
        self.assertEqual(200, confirmed.status_code, confirmed.text)
        self.assertEqual(2, confirmed.json()["reserved_quantity"])
        balance = self.client.get(f"/api/inventory/products/{self.product_id}", headers=self.headers()).json()
        self.assertEqual(5, balance["stock_quantity"])
        self.assertEqual(2, balance["reserved_quantity"])
        self.assertEqual(3, balance["available_quantity"])

        self.assertEqual(
            200,
            self.client.post(
                f"/api/orders/{order['id']}/transition",
                headers=self.headers(),
                json={"to_status": "processing"},
            ).status_code,
        )
        shipped = self.client.post(
            f"/api/orders/{order['id']}/transition",
            headers=self.headers(),
            json={"to_status": "shipped"},
        )
        self.assertEqual(200, shipped.status_code, shipped.text)
        balance = self.client.get(f"/api/inventory/products/{self.product_id}", headers=self.headers()).json()
        self.assertEqual(3, balance["stock_quantity"])
        self.assertEqual(0, balance["reserved_quantity"])

    def test_confirm_rejects_when_available_stock_is_insufficient(self):
        order = self.create_order("SO-INVENTORY-OVER", 6)
        response = self.client.post(
            f"/api/orders/{order['id']}/transition",
            headers=self.headers(),
            json={"to_status": "confirmed"},
        )
        self.assertEqual(409, response.status_code)

    def test_confirm_aggregates_duplicate_product_lines_before_reserving(self):
        created = self.client.post(
            "/api/orders",
            headers=self.headers(),
            json={
                "order_number": "SO-INVENTORY-DUPLICATE-LINES",
                "customer_id": self.customer_id,
                "items": [
                    {"product_id": self.product_id, "quantity": 3},
                    {"product_id": self.product_id, "quantity": 3},
                ],
            },
        )
        self.assertEqual(201, created.status_code, created.text)

        confirmed = self.client.post(
            f"/api/orders/{created.json()['id']}/transition",
            headers=self.headers(),
            json={"to_status": "confirmed"},
        )
        self.assertEqual(409, confirmed.status_code, confirmed.text)

        balance = self.client.get(f"/api/inventory/products/{self.product_id}", headers=self.headers())
        self.assertEqual(5, balance.json()["stock_quantity"])
        self.assertEqual(0, balance.json()["reserved_quantity"])

    def test_cancel_releases_reservation(self):
        order = self.create_order("SO-INVENTORY-CANCEL", 1)
        confirmed = self.client.post(
            f"/api/orders/{order['id']}/transition",
            headers=self.headers(),
            json={"to_status": "confirmed"},
        )
        self.assertEqual(200, confirmed.status_code, confirmed.text)
        cancelled = self.client.post(
            f"/api/orders/{order['id']}/transition",
            headers=self.headers(),
            json={"to_status": "cancelled"},
        )
        self.assertEqual(200, cancelled.status_code, cancelled.text)
        self.assertEqual(0, cancelled.json()["reserved_quantity"])

    def test_refund_after_delivery_restores_stock(self):
        order = self.create_order("SO-INVENTORY-REFUND", 1)
        for status in ("confirmed", "processing", "shipped", "delivered"):
            response = self.client.post(
                f"/api/orders/{order['id']}/transition",
                headers=self.headers(),
                json={"to_status": status},
            )
            self.assertEqual(200, response.status_code, response.text)
        refunded = self.client.post(
            f"/api/orders/{order['id']}/transition",
            headers=self.headers(),
            json={"to_status": "refunded"},
        )
        self.assertEqual(200, refunded.status_code, refunded.text)
        self.assertEqual("refunded", refunded.json()["status"])
        balance = self.client.get(f"/api/inventory/products/{self.product_id}", headers=self.headers()).json()
        self.assertEqual(5, balance["stock_quantity"])


if __name__ == "__main__":
    unittest.main()
