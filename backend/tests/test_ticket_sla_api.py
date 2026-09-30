import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models import Business, Conversation, Customer, Ticket, TicketEvent, User


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
        self.assertIsNotNone(body["first_response_due_at"])

        own = self.client.get("/api/tickets", headers={"X-Business-Id": "1"})
        self.assertEqual(1, own.json()["total"])
        other = self.client.get("/api/tickets", headers={"X-Business-Id": "2"})
        self.assertEqual([], other.json()["items"])

    def test_sla_rules_persist_per_shop_and_drive_new_ticket_deadlines(self):
        headers = {"X-Business-Id": "1"}
        default = self.client.get("/api/tickets/sla/rules", headers=headers)
        self.assertEqual(200, default.status_code, default.text)
        self.assertEqual(2, default.json()["first_response_hours"])
        self.assertEqual(24, default.json()["resolution_hours"])

        saved = self.client.put(
            "/api/tickets/sla/rules",
            headers=headers,
            json={"first_response_hours": 3, "resolution_hours": 36},
        )
        self.assertEqual(200, saved.status_code, saved.text)
        self.assertEqual(3, saved.json()["first_response_hours"])
        self.assertEqual(36, saved.json()["resolution_hours"])

        other_shop = self.client.get("/api/tickets/sla/rules", headers={"X-Business-Id": "2"})
        self.assertEqual(2, other_shop.json()["first_response_hours"])
        self.assertEqual(24, other_shop.json()["resolution_hours"])

        created = self.client.post(
            "/api/tickets",
            headers=headers,
            json={"title": "SLA custom", "customer_id": self.customer_id},
        )
        self.assertEqual(201, created.status_code, created.text)
        body = created.json()
        first_hours = (datetime.fromisoformat(body["first_response_due_at"]) - datetime.fromisoformat(body["created_at"])).total_seconds() / 3600
        resolution_hours = (datetime.fromisoformat(body["sla_due_at"]) - datetime.fromisoformat(body["created_at"])).total_seconds() / 3600
        self.assertAlmostEqual(3, first_hours, delta=0.01)
        self.assertAlmostEqual(36, resolution_hours, delta=0.01)

    def test_sla_rules_reject_out_of_range_values(self):
        response = self.client.put(
            "/api/tickets/sla/rules",
            headers={"X-Business-Id": "1"},
            json={"first_response_hours": 0, "resolution_hours": 721},
        )
        self.assertEqual(422, response.status_code)

    def test_first_response_sla_breach_is_reported_separately(self):
        created = self.client.post(
            "/api/tickets",
            headers={"X-Business-Id": "1"},
            json={"title": "Chưa phản hồi", "customer_id": self.customer_id, "conversation_id": self.conversation_id},
        )
        self.assertEqual(201, created.status_code, created.text)
        ticket_id = created.json()["id"]
        with Session(self.engine) as db:
            ticket = db.get(Ticket, ticket_id)
            ticket.first_response_due_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
            db.commit()

        response = self.client.get("/api/tickets/sla-notifications", headers={"X-Business-Id": "1"})
        self.assertEqual(200, response.status_code, response.text)
        item = next(item for item in response.json()["items"] if item["ticket_id"] == ticket_id)
        self.assertEqual("first_response", item["sla_stage"])

    def test_first_staff_response_closes_the_first_response_sla(self):
        from app.services.ticket_sla import record_first_response

        created = self.client.post(
            "/api/tickets",
            headers={"X-Business-Id": "1"},
            json={"title": "Đã phản hồi", "customer_id": self.customer_id, "conversation_id": self.conversation_id},
        )
        self.assertEqual(201, created.status_code, created.text)
        ticket_id = created.json()["id"]
        responded_at = datetime.now(timezone.utc).replace(tzinfo=None)
        with Session(self.engine) as db:
            record_first_response(db, self.conversation_id, 1, responded_at)
            db.commit()
            ticket = db.get(Ticket, ticket_id)
            self.assertEqual(responded_at, ticket.first_response_at)
            self.assertEqual(
                1,
                db.query(TicketEvent)
                .filter_by(ticket_id=ticket_id, event_type="first_response_recorded")
                .count(),
            )

        notifications = self.client.get("/api/tickets/sla-notifications", headers={"X-Business-Id": "1"})
        self.assertEqual(200, notifications.status_code, notifications.text)
        self.assertFalse(any(
            item["ticket_id"] == ticket_id and item["sla_stage"] == "first_response"
            for item in notifications.json()["items"]
        ))

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
        tenant_tickets = self.client.get("/api/tickets", headers={"X-Business-Id": "1"})
        self.assertEqual(tenant_tickets.json()["total"], response.json()["total_tickets"])
        other = self.client.get("/api/reports/tickets", headers={"X-Business-Id": "2"})
        self.assertEqual(0, other.json()["total_tickets"])


if __name__ == "__main__":
    unittest.main()
