import unittest
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
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

    def test_linear_attribution_reconciles_rounding_remainder(self):
        """Every cent must be allocated even when the split is not exact."""
        with Session(self.engine) as db:
            customer = Customer(
                business_id=self.business_id,
                channel="zalo",
                external_user_id="attr-rounding",
                name="Rounding Buyer",
            )
            db.add(customer)
            db.flush()
            order = Order(
                business_id=self.business_id,
                customer_id=customer.id,
                order_number="ATTR-ROUNDING-001",
                total_amount=Decimal("100.00"),
            )
            db.add(order)
            db.commit()
            customer_id = customer.id
            order_id = order.id

        headers = {"X-Business-Id": str(self.business_id)}
        for source in ("first", "middle", "last"):
            created = self.client.post(
                "/api/revenue/touchpoints",
                headers=headers,
                json={"customer_id": customer_id, "channel": "zalo", "source": source},
            )
            self.assertEqual(201, created.status_code, created.text)

        attributed = self.client.post(
            f"/api/orders/{order_id}/attribution",
            headers=headers,
            json={"model": "linear"},
        )
        self.assertEqual(200, attributed.status_code, attributed.text)
        body = attributed.json()
        self.assertEqual("100.00", body["total_attributed"])
        self.assertEqual(
            ["33.33", "33.33", "33.34"],
            sorted(item["amount"] for item in body["items"]),
        )

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

    def test_conversion_unique_race_is_reported_as_conflict_not_server_error(self):
        with Session(self.engine) as db:
            customer = Customer(
                business_id=self.business_id,
                channel="facebook",
                external_user_id="conversion-race",
                name="Race Buyer",
            )
            db.add(customer)
            db.flush()
            order = Order(
                business_id=self.business_id,
                customer_id=customer.id,
                order_number="ATTR-CONVERSION-RACE",
                total_amount=Decimal("10.00"),
            )
            lead = Lead(
                business_id=self.business_id,
                customer_id=customer.id,
                title="Race lead",
                value=Decimal("10.00"),
            )
            db.add_all([order, lead])
            db.commit()
            order_id = order.id
            lead_id = lead.id

        with patch(
            "app.api.leads.Session.commit",
            side_effect=IntegrityError("INSERT lead_conversions", {}, Exception("duplicate")),
        ):
            response = self.client.post(
                f"/api/leads/{lead_id}/convert",
                headers={"X-Business-Id": str(self.business_id)},
                json={"order_id": order_id},
            )
        self.assertEqual(409, response.status_code, response.text)
        self.assertIn("đã được chuyển đổi", response.json()["detail"])

    def test_reports_accept_consistent_operational_filters(self):
        headers = {"X-Business-Id": str(self.business_id)}
        touchpoint = self.client.post(
            "/api/revenue/touchpoints",
            headers=headers,
            json={
                "customer_id": self.customer_id,
                "conversation_id": self.conversation_id,
                "channel": "facebook",
                "source": "paid-social",
                "campaign": "report-filter",
            },
        )
        self.assertEqual(201, touchpoint.status_code, touchpoint.text)
        attributed = self.client.post(
            f"/api/orders/{self.order_id}/attribution",
            headers=headers,
            json={"model": "last_touch"},
        )
        self.assertEqual(200, attributed.status_code, attributed.text)
        attribution_report = self.client.get(
            "/api/reports/revenue-attribution?model=last_touch&channel=facebook&source=paid-social&campaign=report-filter",
            headers=headers,
        )
        self.assertEqual(200, attribution_report.status_code, attribution_report.text)
        self.assertEqual(1, len(attribution_report.json()["items"]))
        self.assertEqual("facebook", attribution_report.json()["items"][0]["channel"])

        lead = self.client.post(
            "/api/leads",
            headers=headers,
            json={"customer_id": self.customer_id, "title": "Facebook lead", "source_channel": "facebook", "stage": "qualified"},
        )
        self.assertEqual(201, lead.status_code, lead.text)
        pipeline_report = self.client.get("/api/reports/pipeline?channel=facebook&status=open", headers=headers)
        self.assertEqual(200, pipeline_report.status_code, pipeline_report.text)
        self.assertEqual(1, pipeline_report.json()["total_leads"])

        ticket = self.client.post(
            "/api/tickets",
            headers=headers,
            json={"customer_id": self.customer_id, "conversation_id": self.conversation_id, "title": "Telegram ticket", "status": "open"},
        )
        self.assertEqual(201, ticket.status_code, ticket.text)
        ticket_report = self.client.get("/api/reports/tickets?channel=telegram&status=open", headers=headers)
        self.assertEqual(200, ticket_report.status_code, ticket_report.text)
        self.assertEqual(1, ticket_report.json()["total_tickets"])


if __name__ == "__main__":
    unittest.main()
