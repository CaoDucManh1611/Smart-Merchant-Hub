import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models import Business, Conversation, Customer, User


class TicketSlaApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="Support One", slug="support-one")
            two = Business(name="Support Two", slug="support-two")
            db.add_all([one, two])
            db.flush()
            customer = Customer(business_id=one.id, channel="telegram", external_user_id="support-a", name="Buyer A")
            other_customer = Customer(business_id=two.id, channel="facebook", external_user_id="support-b", name="Buyer B")
            agent = User(business_id=one.id, full_name="Agent A", email="agent-a@example.test", is_active=True)
            db.add_all([customer, other_customer, agent])
            db.flush()
            conversation = Conversation(business_id=one.id, customer_id=customer.id, channel="telegram")
            db.add(conversation)
            db.commit()
            cls.customer_id = customer.id
            cls.other_customer_id = other_customer.id
            cls.conversation_id = conversation.id
            cls.agent_id = agent.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_create_ticket_calculates_sla_and_is_tenant_scoped(self):
        response = self.client.post(
            "/api/tickets",
            headers={"X-Business-Id": "1"},
            json={
                "title": "Khách chưa nhận được hàng",
                "description": "Kiểm tra vận đơn giúp tôi",
                "customer_id": self.customer_id,
                "conversation_id": self.conversation_id,
                "priority": "urgent",
                "assigned_user_id": self.agent_id,
            },
        )
        self.assertEqual(201, response.status_code)
        body = response.json()
        self.assertEqual("open", body["status"])
        self.assertEqual("urgent", body["priority"])
        self.assertEqual("telegram", body["channel"])
        self.assertIsNotNone(body["sla_due_at"])

        own = self.client.get("/api/tickets", headers={"X-Business-Id": "1"})
        self.assertEqual(1, own.json()["total"])
        other = self.client.get("/api/tickets", headers={"X-Business-Id": "2"})
        self.assertEqual([], other.json()["items"])

    def test_ticket_rejects_cross_tenant_customer(self):
        response = self.client.post(
            "/api/tickets",
            headers={"X-Business-Id": "1"},
            json={"title": "Invalid", "customer_id": self.other_customer_id},
        )
        self.assertEqual(404, response.status_code)

    def test_resolving_ticket_sets_resolved_at_and_comments_are_history(self):
        tickets = self.client.get("/api/tickets", headers={"X-Business-Id": "1"}).json()["items"]
        ticket_id = tickets[0]["id"]
        updated = self.client.patch(
            f"/api/tickets/{ticket_id}",
            headers={"X-Business-Id": "1"},
            json={"status": "resolved"},
        )
        self.assertEqual(200, updated.status_code)
        self.assertIsNotNone(updated.json()["resolved_at"])

        comment = self.client.post(
            f"/api/tickets/{ticket_id}/comments",
            headers={"X-Business-Id": "1"},
            json={"body": "Đã gửi lại mã vận đơn cho khách."},
        )
        self.assertEqual(201, comment.status_code)
        detail = self.client.get(f"/api/tickets/{ticket_id}", headers={"X-Business-Id": "1"})
        self.assertEqual(1, len(detail.json()["comments"]))

    def test_ticket_report_is_tenant_scoped(self):
        response = self.client.get("/api/reports/tickets", headers={"X-Business-Id": "1"})
        self.assertEqual(200, response.status_code)
        self.assertEqual(1, response.json()["total_tickets"])
        other = self.client.get("/api/reports/tickets", headers={"X-Business-Id": "2"})
        self.assertEqual(0, other.json()["total_tickets"])


if __name__ == "__main__":
    unittest.main()
