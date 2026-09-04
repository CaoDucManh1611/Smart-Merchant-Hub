import unittest
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models import Business, Conversation, Customer, Ticket, User


class CskhAdvancedApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="CSKH One", slug="cskh-one")
            two = Business(name="CSKH Two", slug="cskh-two")
            db.add_all([one, two])
            db.flush()
            customer_a = Customer(
                business_id=one.id,
                channel="telegram",
                external_user_id="cskh-a",
                name="Customer A",
            )
            customer_b = Customer(
                business_id=two.id,
                channel="telegram",
                external_user_id="cskh-b",
                name="Customer B",
            )
            agent_a = User(
                business_id=one.id,
                full_name="Agent A",
                email="agent-a@cskh.test",
                is_active=True,
            )
            agent_b = User(
                business_id=two.id,
                full_name="Agent B",
                email="agent-b@cskh.test",
                is_active=True,
            )
            db.add_all([customer_a, customer_b, agent_a, agent_b])
            db.flush()
            conversation_a = Conversation(
                business_id=one.id,
                customer_id=customer_a.id,
                channel="telegram",
            )
            conversation_b = Conversation(
                business_id=two.id,
                customer_id=customer_b.id,
                channel="telegram",
            )
            db.add_all([conversation_a, conversation_b])
            db.flush()
            db.add_all([
                Ticket(
                    business_id=one.id,
                    customer_id=customer_a.id,
                    conversation_id=conversation_a.id,
                    title="Overdue A",
                    status="open",
                    priority="urgent",
                    sla_due_at=datetime.utcnow() - timedelta(hours=1),
                ),
                Ticket(
                    business_id=two.id,
                    customer_id=customer_b.id,
                    conversation_id=conversation_b.id,
                    title="Overdue B",
                    status="open",
                    priority="urgent",
                    sla_due_at=datetime.utcnow() - timedelta(hours=1),
                ),
            ])
            db.commit()
            cls.business_a = one.id
            cls.business_b = two.id
            cls.customer_a = customer_a.id
            cls.conversation_a = conversation_a.id
            cls.agent_a = agent_a.id
            cls.agent_b = agent_b.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_ticket_history_records_handling_events_and_is_tenant_scoped(self):
        created = self.client.post(
            "/api/tickets",
            headers={"X-Business-Id": str(self.business_a)},
            json={"title": "Theo dõi giao hàng", "customer_id": self.customer_a},
        )
        self.assertEqual(201, created.status_code, created.text)
        ticket_id = created.json()["id"]

        updated = self.client.patch(
            f"/api/tickets/{ticket_id}",
            headers={"X-Business-Id": str(self.business_a)},
            json={"status": "pending", "assigned_user_id": self.agent_a},
        )
        self.assertEqual(200, updated.status_code, updated.text)
        comment = self.client.post(
            f"/api/tickets/{ticket_id}/comments",
            headers={"X-Business-Id": str(self.business_a)},
            json={"body": "Đã gọi cho khách."},
        )
        self.assertEqual(201, comment.status_code, comment.text)

        history = self.client.get(
            f"/api/tickets/{ticket_id}/history",
            headers={"X-Business-Id": str(self.business_a)},
        )
        self.assertEqual(200, history.status_code, history.text)
        self.assertEqual(
            ["created", "status_changed", "assigned", "comment_added"],
            [item["event_type"] for item in history.json()["items"]],
        )
        self.assertTrue(all(item["business_id"] == self.business_a for item in history.json()["items"]))

        cross_tenant = self.client.get(
            f"/api/tickets/{ticket_id}/history",
            headers={"X-Business-Id": str(self.business_b)},
        )
        self.assertEqual(404, cross_tenant.status_code)

    def test_sla_notifications_return_only_overdue_tickets_for_current_tenant(self):
        response = self.client.get(
            "/api/tickets/sla-notifications",
            headers={"X-Business-Id": str(self.business_a)},
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(1, response.json()["total"])
        self.assertEqual("Overdue A", response.json()["items"][0]["title"])

        other = self.client.get(
            "/api/tickets/sla-notifications",
            headers={"X-Business-Id": str(self.business_b)},
        )
        self.assertEqual(1, other.json()["total"])
        self.assertEqual("Overdue B", other.json()["items"][0]["title"])

    def test_conversation_reassignment_validates_tenant_and_records_assignment(self):
        response = self.client.patch(
            f"/api/conversations/{self.conversation_a}/assignment",
            headers={"X-Business-Id": str(self.business_a)},
            json={"assigned_user_id": self.agent_a},
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(self.agent_a, response.json()["assigned_user_id"])

        assignment_history = self.client.get(
            f"/api/conversations/{self.conversation_a}/assignments",
            headers={"X-Business-Id": str(self.business_a)},
        )
        self.assertEqual(200, assignment_history.status_code, assignment_history.text)
        self.assertEqual(1, assignment_history.json()["total"])
        self.assertEqual(self.agent_a, assignment_history.json()["items"][0]["user_id"])

        cross_tenant = self.client.patch(
            f"/api/conversations/{self.conversation_a}/assignment",
            headers={"X-Business-Id": str(self.business_a)},
            json={"assigned_user_id": self.agent_b},
        )
        self.assertEqual(404, cross_tenant.status_code)

        with Session(self.engine) as db:
            conversation = db.get(Conversation, self.conversation_a)
            self.assertEqual(self.agent_a, conversation.assigned_user_id)
            self.assertEqual(1, len(conversation.assignments))


if __name__ == "__main__":
    unittest.main()
