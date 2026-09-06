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


class OrderPaymentApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Payments", slug="payments")
            db.add(business)
            db.flush()
            customer = Customer(
                business_id=business.id,
                channel="telegram",
                external_user_id="payment-customer",
                name="Payment Buyer",
            )
            product = Product(
                business_id=business.id,
                sku="PAY-01",
                name="Payment Product",
                price=100,
                stock_quantity=10,
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

    def create_order(self, order_number="SO-PAY"):
        response = self.client.post(
            "/api/orders",
            headers=self.headers(),
            json={
                "order_number": order_number,
                "customer_id": self.customer_id,
                "items": [{"product_id": self.product_id, "quantity": 1}],
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        return response.json()

    def test_partial_payment_updates_summary_and_is_idempotent(self):
        order = self.create_order("SO-PAY-PARTIAL")
        payload = {
            "idempotency_key": "pay-partial-1",
            "amount": "25.00",
            "method": "bank_transfer",
            "status": "paid",
        }
        first = self.client.post(
            f"/api/orders/{order['id']}/payments",
            headers=self.headers(),
            json=payload,
        )
        self.assertEqual(201, first.status_code, first.text)
        self.assertEqual("partial", first.json()["order"]["payment_status"])
        self.assertEqual("25.00", first.json()["order"]["paid_amount"])

        second = self.client.post(
            f"/api/orders/{order['id']}/payments",
            headers=self.headers(),
            json=payload,
        )
        self.assertEqual(200, second.status_code, second.text)
        self.assertEqual(first.json()["payment"]["id"], second.json()["payment"]["id"])
        self.assertEqual("25.00", second.json()["order"]["paid_amount"])

    def test_payment_cannot_overpay_and_refund_is_bounded(self):
        order = self.create_order("SO-PAY-REFUND")
        payment = self.client.post(
            f"/api/orders/{order['id']}/payments",
            headers=self.headers(),
            json={
                "idempotency_key": "pay-full-1",
                "amount": "100.00",
                "method": "cash",
                "status": "paid",
            },
        )
        self.assertEqual(201, payment.status_code, payment.text)
        self.assertEqual("paid", payment.json()["order"]["payment_status"])

        overpay = self.client.post(
            f"/api/orders/{order['id']}/payments",
            headers=self.headers(),
            json={
                "idempotency_key": "pay-over-1",
                "amount": "1.00",
                "method": "cash",
                "status": "paid",
            },
        )
        self.assertEqual(409, overpay.status_code, overpay.text)

        refund_payload = {"idempotency_key": "refund-1", "amount": "100.00", "reason": "Khách hoàn đơn"}
        refund = self.client.post(
            f"/api/orders/{order['id']}/refunds",
            headers=self.headers(),
            json=refund_payload,
        )
        self.assertEqual(201, refund.status_code, refund.text)
        self.assertEqual("refunded", refund.json()["order"]["payment_status"])
        self.assertEqual("100.00", refund.json()["order"]["refunded_amount"])

        duplicate = self.client.post(
            f"/api/orders/{order['id']}/refunds",
            headers=self.headers(),
            json=refund_payload,
        )
        self.assertEqual(200, duplicate.status_code, duplicate.text)
        self.assertEqual(refund.json()["payment"]["id"], duplicate.json()["payment"]["id"])

        over_refund = self.client.post(
            f"/api/orders/{order['id']}/refunds",
            headers=self.headers(),
            json={"idempotency_key": "refund-over-1", "amount": "0.01", "reason": "Sai số"},
        )
        self.assertEqual(409, over_refund.status_code, over_refund.text)

    def test_order_events_include_payment_and_refund(self):
        order = self.create_order("SO-PAY-EVENTS")
        self.client.post(
            f"/api/orders/{order['id']}/payments",
            headers=self.headers(),
            json={"idempotency_key": "pay-event-1", "amount": "100", "method": "cash", "status": "paid"},
        )
        self.client.post(
            f"/api/orders/{order['id']}/refunds",
            headers=self.headers(),
            json={"idempotency_key": "refund-event-1", "amount": "10", "reason": "Đổi hàng"},
        )
        events = self.client.get(f"/api/orders/{order['id']}/events", headers=self.headers())
        self.assertEqual(200, events.status_code, events.text)
        event_types = {item["event_type"] for item in events.json()["items"]}
        self.assertIn("payment_created", event_types)
        self.assertIn("refund_created", event_types)

    def test_order_cannot_complete_until_fully_paid(self):
        order = self.create_order("SO-PAY-COMPLETE")
        for status in ("confirmed", "processing", "shipped", "delivered"):
            transition = self.client.post(
                f"/api/orders/{order['id']}/transition",
                headers=self.headers(),
                json={"to_status": status},
            )
            self.assertEqual(200, transition.status_code, transition.text)

        unpaid_completion = self.client.post(
            f"/api/orders/{order['id']}/transition",
            headers=self.headers(),
            json={"to_status": "completed"},
        )
        self.assertEqual(409, unpaid_completion.status_code, unpaid_completion.text)

        payment = self.client.post(
            f"/api/orders/{order['id']}/payments",
            headers=self.headers(),
            json={
                "idempotency_key": "pay-complete-1",
                "amount": "100.00",
                "method": "cash",
                "status": "paid",
            },
        )
        self.assertEqual(201, payment.status_code, payment.text)

        completed = self.client.post(
            f"/api/orders/{order['id']}/transition",
            headers=self.headers(),
            json={"to_status": "completed"},
        )
        self.assertEqual(200, completed.status_code, completed.text)
        self.assertEqual("completed", completed.json()["status"])


if __name__ == "__main__":
    unittest.main()
