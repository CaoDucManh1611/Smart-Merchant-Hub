import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.customer import Customer
from app.models.sales import Order
from app.models.ticket import Ticket


class CustomerNextActionsApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            business = Business(name="Next Actions Test", slug="next-actions-test")
            other = Business(name="Other Next Actions Test", slug="other-next-actions-test")
            db.add_all([business, other])
            db.flush()
            customer = Customer(
                business_id=business.id,
                channel="facebook",
                external_user_id="test-customer",
                name="Private Customer Name",
                email="private@example.com",
                phone="0901234567",
            )
            other_customer = Customer(
                business_id=other.id,
                channel="instagram",
                external_user_id="other-customer",
            )
            db.add_all([customer, other_customer])
            db.flush()
            db.add(Order(
                business_id=business.id,
                customer_id=customer.id,
                order_number="DRAFT-ONLY",
                status="draft",
                total_amount=999999,
                refunded_amount=0,
                payment_status="unpaid",
            ))
            db.commit()
            self.business_id = business.id
            self.customer_id = customer.id
            self.other_business_id = other.id
            self.other_customer_id = other_customer.id

        def override_get_db():
            with Session(self.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.engine.dispose()

    def headers(self, business_id=None):
        return {"X-Business-Id": str(business_id or self.business_id)}

    def test_provider_failure_falls_back_and_ignores_draft_order(self):
        with patch("app.services.customer_next_actions.call_llm", side_effect=RuntimeError("quota")):
            response = self.client.post(
                f"/api/customers/{self.customer_id}/next-actions",
                headers=self.headers(),
                json={"language": "vi"},
            )

        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual("rules", body["source"])
        self.assertEqual(0, body["signals"]["completed_orders"])
        self.assertEqual(0, body["signals"]["net_spend"])
        self.assertNotIn("999999", str(body))
        self.assertTrue(body["actions"])

    def test_ai_suggestions_are_grounded_and_customer_identifiers_are_not_sent(self):
        raw = (
            '{"actions":[{"title":"Ask what they need","reason":"No completed order is recorded.",'
            '"next_step":"Ask about their needs.","draft_message":"What can we help you find?",'
            '"priority":"normal","evidence_keys":["completed_orders","invented_signal"]}]}'
        )
        with patch("app.services.customer_next_actions.call_llm", return_value=raw) as llm:
            response = self.client.post(
                f"/api/customers/{self.customer_id}/next-actions",
                headers=self.headers(),
                json={"language": "en"},
            )

        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual("ai", body["source"])
        self.assertEqual("Completed orders", body["actions"][0]["evidence"][0]["label"])
        self.assertEqual(["completed_orders"], [item["key"] for item in body["actions"][0]["evidence"]])
        prompt_text = str(llm.call_args.args[0])
        self.assertNotIn("Private Customer Name", prompt_text)
        self.assertNotIn("private@example.com", prompt_text)
        self.assertNotIn("0901234567", prompt_text)

    def test_customer_from_another_shop_is_not_accessible(self):
        response = self.client.post(
            f"/api/customers/{self.other_customer_id}/next-actions",
            headers=self.headers(),
            json={"language": "vi"},
        )
        self.assertEqual(404, response.status_code)

    def test_open_ticket_suppresses_sales_and_prevents_reasking_for_details(self):
        with Session(self.engine) as db:
            db.add(Ticket(
                business_id=self.business_id,
                customer_id=self.customer_id,
                title="Customer already described the issue",
                status="open",
            ))
            db.commit()

        raw = (
            '{"actions":[{"title":"Handle support ticket","reason":"One ticket is open.",'
            '"next_step":"Review the ticket first.","draft_message":"Please tell us the details again.",'
            '"priority":"high","evidence_keys":["open_tickets"]},'
            '{"title":"Upsell","reason":"Offer more products.","next_step":"Sell now.",'
            '"draft_message":"Buy this too.","priority":"normal","evidence_keys":["completed_orders"]}]}'
        )
        with patch("app.services.customer_next_actions.call_llm", return_value=raw):
            response = self.client.post(
                f"/api/customers/{self.customer_id}/next-actions",
                headers=self.headers(),
                json={"language": "en"},
            )

        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual("ai", body["source"])
        self.assertEqual(1, len(body["actions"]))
        self.assertEqual(["open_tickets"], [item["key"] for item in body["actions"][0]["evidence"]])
        self.assertEqual("Prioritize the open support request", body["actions"][0]["title"])
        self.assertEqual("high", body["actions"][0]["priority"])
        self.assertEqual("Review the ticket, handle the issue, and update the customer.", body["actions"][0]["next_step"])
        self.assertEqual("", body["actions"][0]["draft_message"])


if __name__ == "__main__":
    unittest.main()
