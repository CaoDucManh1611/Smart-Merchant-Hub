import unittest
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models import Business, Conversation, Customer, Lead, Order, Product, OrderItem


class CrmAttributionPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="Attribution One", slug="attribution-one")
            two = Business(name="Attribution Two", slug="attribution-two")
            db.add_all([one, two])
            db.flush()
            customer = Customer(business_id=one.id, channel="telegram", external_user_id="attr-a", name="Attr Buyer")
            other_customer = Customer(business_id=two.id, channel="facebook", external_user_id="attr-b", name="Other Buyer")
            db.add_all([customer, other_customer])
            db.flush()
            conversation = Conversation(business_id=one.id, customer_id=customer.id, channel="telegram")
            db.add(conversation)
            db.flush()
            product = Product(business_id=one.id, sku="ATTR-01", name="Attribution Product", price=Decimal("100"), stock_quantity=10)
            db.add(product)
            db.flush()
            order = Order(business_id=one.id, customer_id=customer.id, conversation_id=conversation.id, order_number="ATTR-001", total_amount=Decimal("100"))
            db.add(order)
            db.flush()
            db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=1, unit_price=Decimal("100"), line_total=Decimal("100")))
            lead = Lead(business_id=one.id, customer_id=customer.id, conversation_id=conversation.id, title="Attr lead", value=Decimal("100"))
            db.add(lead)
            db.commit()
            cls.business_id = one.id
            cls.other_business_id = two.id
            cls.customer_id = customer.id
            cls.conversation_id = conversation.id
            cls.order_id = order.id
            cls.lead_id = lead.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_linear_attribution_splits_order_and_is_tenant_scoped(self):
        headers = {"X-Business-Id": str(self.business_id)}
        first = self.client.post(
            "/api/revenue/touchpoints",
            headers=headers,
            json={"customer_id": self.customer_id, "conversation_id": self.conversation_id, "channel": "telegram", "source": "organic"},
        )
        self.assertEqual(201, first.status_code, first.text)
        second = self.client.post(
            "/api/revenue/touchpoints",
            headers=headers,
            json={"customer_id": self.customer_id, "conversation_id": self.conversation_id, "channel": "telegram", "source": "campaign", "campaign": "launch"},
        )
        self.assertEqual(201, second.status_code, second.text)
        attributed = self.client.post(
            f"/api/orders/{self.order_id}/attribution",
            headers=headers,
            json={"model": "linear"},
        )
        self.assertEqual(200, attributed.status_code, attributed.text)
        body = attributed.json()
        self.assertEqual("linear", body["model"])
        self.assertEqual("100.00", body["total_attributed"])
        self.assertEqual(["50.00", "50.00"], sorted(item["amount"] for item in body["items"]))
        hidden = self.client.get("/api/revenue/touchpoints", headers={"X-Business-Id": str(self.other_business_id)})
        self.assertEqual(200, hidden.status_code)
        self.assertEqual([], hidden.json()["items"])

    def test_lead_activity_and_conversion_are_explicit(self):
        headers = {"X-Business-Id": str(self.business_id)}
        activity = self.client.post(
            f"/api/leads/{self.lead_id}/activities",
            headers=headers,
            json={"activity_type": "call", "subject": "Follow up", "body": "Discussed requirements"},
        )
        self.assertEqual(201, activity.status_code, activity.text)
        activities = self.client.get(f"/api/leads/{self.lead_id}/activities", headers=headers)
        self.assertEqual(200, activities.status_code)
        self.assertEqual("call", activities.json()["items"][0]["activity_type"])
        converted = self.client.post(
            f"/api/leads/{self.lead_id}/convert",
            headers=headers,
            json={"order_id": self.order_id},
        )
        self.assertEqual(201, converted.status_code, converted.text)
        duplicate = self.client.post(
            f"/api/leads/{self.lead_id}/convert",
            headers=headers,
            json={"order_id": self.order_id},
        )
        self.assertEqual(409, duplicate.status_code)


if __name__ == "__main__":
    unittest.main()
