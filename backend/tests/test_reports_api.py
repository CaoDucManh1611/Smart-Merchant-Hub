import unittest
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business, User
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.lead import Lead
from app.models.sales import Order
from app.models.ticket import Ticket


class ReportsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="Reports One", slug="reports-one")
            two = Business(name="Reports Two", slug="reports-two")
            db.add_all([one, two])
            db.flush()
            agent = User(
                business_id=one.id,
                full_name="Agent One",
                email="agent@reports.test",
                role="agent",
            )
            customer = Customer(
                business_id=one.id,
                channel="telegram",
                external_user_id="report-customer",
            )
            other_customer = Customer(
                business_id=two.id,
                channel="telegram",
                external_user_id="other-report-customer",
            )
            db.add_all([agent, customer, other_customer])
            db.flush()
            conversation = Conversation(
                business_id=one.id,
                customer_id=customer.id,
                channel="telegram",
                assigned_user_id=agent.id,
            )
            other_conversation = Conversation(
                business_id=two.id,
                customer_id=other_customer.id,
                channel="telegram",
            )
            db.add_all([conversation, other_conversation])
            db.flush()
            db.add_all([
                Lead(
                    business_id=one.id,
                    customer_id=customer.id,
                    conversation_id=conversation.id,
                    title="Won lead",
                    stage="won",
                    value=Decimal("100000"),
                    assigned_user_id=agent.id,
                ),
                Lead(
                    business_id=one.id,
                    customer_id=customer.id,
                    conversation_id=conversation.id,
                    title="Open lead",
                    stage="qualified",
                    value=Decimal("200000"),
                ),
                Lead(
                    business_id=two.id,
                    customer_id=other_customer.id,
                    title="Other lead",
                    stage="won",
                    value=Decimal("999999"),
                ),
                Ticket(
                    business_id=one.id,
                    customer_id=customer.id,
                    conversation_id=conversation.id,
                    title="Question",
                    assigned_user_id=agent.id,
                    status="resolved",
                ),
                Ticket(
                    business_id=two.id,
                    customer_id=other_customer.id,
                    title="Other ticket",
                    status="open",
                ),
                Order(
                    business_id=one.id,
                    customer_id=customer.id,
                    conversation_id=conversation.id,
                    order_number="REPORT-001",
                    status="paid",
                    total_amount=Decimal("150000"),
                ),
            ])
            db.commit()
            cls.agent_id = agent.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_overview_reports_tenant_counts_and_conversion_rates(self):
        response = self.client.get("/api/reports/overview", headers={"X-Business-Id": "1"})
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertEqual(1, body["customer_count"])
        self.assertEqual(1, body["conversation_count"])
        self.assertEqual(2, body["lead_count"])
        self.assertEqual(1, body["ticket_count"])
        self.assertEqual(1, body["order_count"])
        self.assertEqual("150000.00", body["total_revenue"])
        self.assertEqual(50.0, body["conversion_rate"])
        self.assertEqual(100.0, body["conversation_to_order_rate"])

        other = self.client.get("/api/reports/overview", headers={"X-Business-Id": "2"})
        self.assertEqual(200, other.status_code)
        self.assertEqual(1, other.json()["lead_count"])
        self.assertEqual(0, other.json()["order_count"])

    def test_agent_performance_is_tenant_scoped(self):
        response = self.client.get("/api/reports/agent-performance", headers={"X-Business-Id": "1"})
        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        agent = next(item for item in body["items"] if item["user_id"] == self.agent_id)
        self.assertEqual(1, agent["assigned_conversations"])
        self.assertEqual(1, agent["assigned_tickets"])
        self.assertEqual(1, agent["assigned_leads"])
        self.assertEqual(1, agent["resolved_tickets"])
        self.assertEqual(1, agent["won_leads"])

        other = self.client.get("/api/reports/agent-performance", headers={"X-Business-Id": "2"})
        self.assertEqual(200, other.status_code)
        self.assertEqual([], other.json()["items"])


if __name__ == "__main__":
    unittest.main()
