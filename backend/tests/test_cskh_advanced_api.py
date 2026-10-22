import unittest
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.passwords import hash_password
from app.db.dependencies import get_db
from app.main import app
from app.models import Business, Conversation, Customer, Ticket, User
from app.models.permission import PermissionOverride


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
                password_hash=hash_password("agent-password"),
                is_active=True,
            )
            agent_b = User(
                business_id=two.id,
                full_name="Agent B",
                email="agent-b@cskh.test",
                is_active=True,
            )
            owner_a = User(
                business_id=one.id,
                full_name="Owner A",
                email="owner-a@cskh.test",
                role="owner",
                password_hash=hash_password("owner-password"),
                is_active=True,
            )
            support_a = User(
                business_id=one.id,
                full_name="Support A",
                email="support-a@cskh.test",
                role="support",
                password_hash=hash_password("support-password"),
                is_active=True,
            )
            db.add_all([customer_a, customer_b, agent_a, agent_b, owner_a, support_a])
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
                    sla_due_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1),
                ),
                Ticket(
                    business_id=two.id,
                    customer_id=customer_b.id,
                    conversation_id=conversation_b.id,
                    title="Overdue B",
                    status="open",
                    priority="urgent",
                    sla_due_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1),
                ),
            ])
            db.commit()
            cls.business_a = one.id
            cls.business_b = two.id
            cls.customer_a = customer_a.id
            cls.conversation_a = conversation_a.id
            cls.agent_a = agent_a.id
            cls.agent_b = agent_b.id
            cls.owner_a = owner_a.id
            cls.support_a = support_a.id

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

    def test_conversation_priority_is_persisted_and_tenant_scoped(self):
        headers = {"X-Business-Id": str(self.business_a)}
        updated = self.client.patch(
            f"/api/conversations/{self.conversation_a}/priority",
            headers=headers,
            json={"is_priority": True},
        )
        self.assertEqual(200, updated.status_code, updated.text)
        self.assertEqual("high", updated.json()["priority"])

        inbox = self.client.get("/api/conversations", headers=headers)
        self.assertEqual(200, inbox.status_code, inbox.text)
        self.assertEqual("high", inbox.json()["items"][0]["priority"])

        cleared = self.client.patch(
            f"/api/conversations/{self.conversation_a}/priority",
            headers=headers,
            json={"is_priority": False},
        )
        self.assertEqual(200, cleared.status_code, cleared.text)
        self.assertEqual("normal", cleared.json()["priority"])

        cross_tenant = self.client.patch(
            f"/api/conversations/{self.conversation_a}/priority",
            headers={"X-Business-Id": str(self.business_b)},
            json={"is_priority": True},
        )
        self.assertEqual(404, cross_tenant.status_code)

    def test_agent_cannot_change_shop_sla_rules(self):
        login = self.client.post(
            "/api/auth/login",
            headers={"X-Business-Id": str(self.business_a)},
            json={"email": "agent-a@cskh.test", "password": "agent-password"},
        )
        self.assertEqual(200, login.status_code, login.text)
        response = self.client.put(
            "/api/tickets/sla/rules",
            headers={
                "Authorization": "{0} {1}".format("Bearer", login.json()["access_token"]),
                "X-Business-Id": str(self.business_a),
            },
            json={"first_response_hours": 4, "resolution_hours": 48},
        )
        self.assertEqual(403, response.status_code, response.text)

        with Session(self.engine) as db:
            db.add(PermissionOverride(
                business_id=self.business_a,
                resource="tickets",
                action="read",
                effect="deny",
                role="agent",
            ))
            db.commit()
        denied_read = self.client.get(
            "/api/tickets",
            headers={
                "Authorization": "{0} {1}".format("Bearer", login.json()["access_token"]),
                "X-Business-Id": str(self.business_a),
            },
        )
        self.assertEqual(403, denied_read.status_code, denied_read.text)

    def test_shop_support_role_can_handle_tickets_but_not_change_sla_rules(self):
        login = self.client.post(
            "/api/auth/login",
            headers={"X-Business-Id": str(self.business_a)},
            json={"email": "support-a@cskh.test", "password": "support-password"},
        )
        self.assertEqual(200, login.status_code, login.text)
        headers = {
            "Authorization": "{0} {1}".format("Bearer", login.json()["access_token"]),
            "X-Business-Id": str(self.business_a),
        }

        identity = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(200, identity.status_code, identity.text)
        listing = self.client.get("/api/tickets", headers=headers)
        self.assertEqual(200, listing.status_code, listing.text)
        ticket_id = listing.json()["items"][0]["id"]
        updated = self.client.patch(
            f"/api/tickets/{ticket_id}",
            headers=headers,
            json={"status": "pending", "assigned_user_id": self.support_a},
        )
        self.assertEqual(200, updated.status_code, updated.text)
        comment = self.client.post(
            f"/api/tickets/{ticket_id}/comments",
            headers=headers,
            json={"body": "Đã tiếp nhận và đang kiểm tra."},
        )
        self.assertEqual(201, comment.status_code, comment.text)

        sla_update = self.client.put(
            "/api/tickets/sla/rules",
            headers=headers,
            json={"first_response_hours": 4, "resolution_hours": 48},
        )
        self.assertEqual(403, sla_update.status_code, sla_update.text)

    def test_ticket_write_deny_override_is_enforced_for_staff(self):
        with Session(self.engine) as db:
            db.add(PermissionOverride(
                business_id=self.business_a,
                resource="tickets",
                action="write",
                effect="deny",
                role="agent",
            ))
            db.commit()

        login = self.client.post(
            "/api/auth/login",
            headers={"X-Business-Id": str(self.business_a)},
            json={"email": "agent-a@cskh.test", "password": "agent-password"},
        )
        self.assertEqual(200, login.status_code, login.text)
        response = self.client.post(
            "/api/tickets",
            headers={
                "Authorization": "{0} {1}".format("Bearer", login.json()["access_token"]),
                "X-Business-Id": str(self.business_a),
            },
            json={"title": "Restricted ticket", "customer_id": self.customer_a},
        )
        self.assertEqual(403, response.status_code, response.text)

    def test_authenticated_ticket_scope_ignores_foreign_business_header(self):
        login = self.client.post(
            "/api/auth/login",
            headers={"X-Business-Id": str(self.business_a)},
            json={"email": "owner-a@cskh.test", "password": "owner-password"},
        )
        self.assertEqual(200, login.status_code, login.text)
        headers = {
            "Authorization": "{0} {1}".format("Bearer", login.json()["access_token"]),
            "X-Business-Id": str(self.business_b),
        }
        with Session(self.engine) as db:
            foreign_ticket_id = db.query(Ticket.id).filter(
                Ticket.business_id == self.business_b,
            ).scalar()

        listing = self.client.get("/api/tickets", headers=headers)
        self.assertEqual(200, listing.status_code, listing.text)
        self.assertTrue(all(item["business_id"] == self.business_a for item in listing.json()["items"]))
        self.assertFalse(any(item["title"] == "Overdue B" for item in listing.json()["items"]))

        detail = self.client.get(f"/api/tickets/{foreign_ticket_id}", headers=headers)
        self.assertEqual(404, detail.status_code, detail.text)
        update = self.client.patch(
            f"/api/tickets/{foreign_ticket_id}",
            headers=headers,
            json={"status": "resolved"},
        )
        self.assertEqual(404, update.status_code, update.text)

    def test_authenticated_handling_history_keeps_actor_attribution(self):
        login = self.client.post(
            "/api/auth/login",
            headers={"X-Business-Id": str(self.business_a)},
            json={"email": "owner-a@cskh.test", "password": "owner-password"},
        )
        self.assertEqual(200, login.status_code, login.text)
        headers = {
            "Authorization": f"Bearer {login.json()['access_token']}",
            "X-Business-Id": str(self.business_a),
        }

        created = self.client.post(
            "/api/tickets",
            headers=headers,
            json={"title": "Cần cập nhật người xử lý", "customer_id": self.customer_a},
        )
        self.assertEqual(201, created.status_code, created.text)
        ticket_id = created.json()["id"]

        updated = self.client.patch(
            f"/api/tickets/{ticket_id}",
            headers=headers,
            json={"status": "pending", "assigned_user_id": self.agent_a},
        )
        self.assertEqual(200, updated.status_code, updated.text)

        comment = self.client.post(
            f"/api/tickets/{ticket_id}/comments",
            headers=headers,
            json={"body": "Đã bàn giao cho nhân viên."},
        )
        self.assertEqual(201, comment.status_code, comment.text)
        self.assertEqual(self.owner_a, comment.json()["author_user_id"])

        history = self.client.get(f"/api/tickets/{ticket_id}/history", headers=headers)
        self.assertEqual(200, history.status_code, history.text)
        self.assertTrue(all(item["actor_user_id"] == self.owner_a for item in history.json()["items"]))

        reassigned = self.client.patch(
            f"/api/conversations/{self.conversation_a}/assignment",
            headers=headers,
            json={"assigned_user_id": self.agent_a},
        )
        self.assertEqual(200, reassigned.status_code, reassigned.text)
        assignments = self.client.get(
            f"/api/conversations/{self.conversation_a}/assignments",
            headers=headers,
        )
        self.assertEqual(200, assignments.status_code, assignments.text)
        self.assertEqual(self.owner_a, assignments.json()["items"][-1]["assigned_by"])

        audit_logs = self.client.get("/api/auth/audit-logs", headers=headers)
        self.assertEqual(200, audit_logs.status_code, audit_logs.text)
        actions = {row["action"] for row in audit_logs.json()}
        self.assertTrue({"conversation_assignment", "ticket_created", "ticket_updated", "ticket_comment"}.issubset(actions))


if __name__ == "__main__":
    unittest.main()
