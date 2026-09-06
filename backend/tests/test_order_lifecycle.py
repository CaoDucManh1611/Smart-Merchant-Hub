import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.customer import Customer
from app.models.sales import Order, OrderItem, Product


class OrderLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Order Life", slug="order-life")
            db.add(business)
            db.flush()
            customer = Customer(business_id=business.id, channel="telegram", external_user_id="life-user")
            product = Product(business_id=business.id, sku="LIFE", name="Life", price=10, stock_quantity=1)
            db.add_all([customer, product])
            db.flush()
            order = Order(
                business_id=business.id,
                customer_id=customer.id,
                order_number="SO-LIFE",
                status="draft",
                total_amount=10,
            )
            db.add(order)
            db.flush()
            db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=1, unit_price=10, line_total=10))
            db.commit()
            cls.business_id = business.id
            cls.order_id = order.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_sales_order_transition_graph(self):
        headers = {"X-Business-Id": str(self.business_id)}
        response = self.client.post(
            f"/api/orders/{self.order_id}/transition",
            headers=headers,
            json={"to_status": "confirmed"},
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("confirmed", response.json()["status"])

        invalid = self.client.post(
            f"/api/orders/{self.order_id}/transition",
            headers=headers,
            json={"to_status": "delivered"},
        )
        self.assertEqual(409, invalid.status_code)


if __name__ == "__main__":
    unittest.main()
