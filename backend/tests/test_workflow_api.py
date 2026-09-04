import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models import Business, Conversation, Customer, User
from app.models.crm_extended import CustomerTag


class WorkflowApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="Workflow One", slug="workflow-one")
            two = Business(name="Workflow Two", slug="workflow-two")
            db.add_all([one, two])
            db.flush()
            customer = Customer(business_id=one.id, channel="telegram", external_user_id="wf-user")
            db.add(customer)
            db.flush()
            conversation = Conversation(business_id=one.id, customer_id=customer.id, channel="telegram")
            db.add(conversation)
            db.commit()
            cls.business_one = one.id
            cls.business_two = two.id
            cls.customer_id = customer.id
            cls.conversation_id = conversation.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_workflows_are_tenant_scoped(self):
        created = self.client.post(
            "/api/workflows",
            headers={"X-Business-Id": str(self.business_one)},
            json={
                "name": "Telegram follow-up",
                "event_type": "message.created",
                "conditions": {"channel": "telegram"},
                "actions": [{"type": "create_ticket", "title": "Gọi lại khách"}],
            },
        )
        self.assertEqual(201, created.status_code)
        workflow_id = created.json()["id"]
        self.assertEqual(self.business_one, created.json()["business_id"])

        own = self.client.get("/api/workflows", headers={"X-Business-Id": str(self.business_one)})
        self.assertGreaterEqual(own.json()["total"], 1)
        self.assertIn("Telegram follow-up", [item["name"] for item in own.json()["items"]])
        other = self.client.get("/api/workflows", headers={"X-Business-Id": str(self.business_two)})
        self.assertEqual([], other.json()["items"])
        cross_tenant = self.client.get(
            f"/api/workflows/{workflow_id}",
            headers={"X-Business-Id": str(self.business_two)},
        )
        self.assertEqual(404, cross_tenant.status_code)

    def test_matching_workflow_runs_once_and_creates_ticket(self):
        created = self.client.post(
            "/api/workflows",
            headers={"X-Business-Id": str(self.business_one)},
            json={
                "name": "Urgent Telegram follow-up",
                "event_type": "message.created",
                "conditions": {"channel": "telegram"},
                "actions": [{"type": "create_ticket", "title": "Follow up", "priority": "high"}],
            },
        )
        workflow_id = created.json()["id"]
        event = {
            "event_id": "message-100",
            "event_type": "message.created",
            "payload": {
                "channel": "telegram",
                "customer_id": self.customer_id,
                "conversation_id": self.conversation_id,
            },
        }
        first = self.client.post(
            f"/api/workflows/{workflow_id}/run",
            headers={"X-Business-Id": str(self.business_one)},
            json=event,
        )
        self.assertEqual(200, first.status_code)
        self.assertEqual("completed", first.json()["status"])

        duplicate = self.client.post(
            f"/api/workflows/{workflow_id}/run",
            headers={"X-Business-Id": str(self.business_one)},
            json=event,
        )
        self.assertEqual(200, duplicate.status_code)
        self.assertEqual("duplicate", duplicate.json()["status"])
        tickets = self.client.get("/api/tickets", headers={"X-Business-Id": str(self.business_one)})
        self.assertEqual(1, tickets.json()["total"])

    def test_condition_mismatch_does_not_execute(self):
        created = self.client.post(
            "/api/workflows",
            headers={"X-Business-Id": str(self.business_one)},
            json={
                "name": "Facebook only",
                "event_type": "message.created",
                "conditions": {"channel": "facebook"},
                "actions": [{"type": "create_ticket", "title": "Không nên tạo"}],
            },
        )
        response = self.client.post(
            f"/api/workflows/{created.json()['id']}/run",
            headers={"X-Business-Id": str(self.business_one)},
            json={
                "event_id": "message-101",
                "event_type": "message.created",
                "payload": {"channel": "telegram", "customer_id": self.customer_id},
            },
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("skipped", response.json()["status"])

    def test_add_tag_action_creates_customer_tag(self):
        created = self.client.post(
            "/api/workflows",
            headers={"X-Business-Id": str(self.business_one)},
            json={
                "name": "Mark Telegram customer",
                "event_type": "message.created",
                "conditions": {"channel": "telegram"},
                "actions": [{"type": "add_tag", "tag": "VIP"}],
            },
        )
        self.assertEqual(201, created.status_code)
        response = self.client.post(
            f"/api/workflows/{created.json()['id']}/run",
            headers={"X-Business-Id": str(self.business_one)},
            json={
                "event_id": "message-tag-1",
                "event_type": "message.created",
                "payload": {
                    "channel": "telegram",
                    "customer_id": self.customer_id,
                    "conversation_id": self.conversation_id,
                },
            },
        )
        self.assertEqual("completed", response.json()["status"])
        with Session(self.engine) as db:
            tags = db.query(CustomerTag).filter(
                CustomerTag.business_id == self.business_one,
                CustomerTag.customer_id == self.customer_id,
            ).all()
            self.assertEqual(1, len(tags))

    def test_invalid_event_and_action_are_rejected(self):
        invalid_event = self.client.post(
            "/api/workflows",
            headers={"X-Business-Id": str(self.business_one)},
            json={"name": "Bad", "event_type": "unknown.event", "actions": []},
        )
        self.assertEqual(422, invalid_event.status_code)
        invalid_action = self.client.post(
            "/api/workflows",
            headers={"X-Business-Id": str(self.business_one)},
            json={
                "name": "Bad action",
                "event_type": "message.created",
                "actions": [{"type": "send_external_message"}],
            },
        )
        self.assertEqual(422, invalid_action.status_code)


if __name__ == "__main__":
    unittest.main()
