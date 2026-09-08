import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.conversation import Conversation
from app.models.customer import Customer


class ChatbotRuntimeApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            first = Business(name="Runtime One", slug="runtime-one")
            second = Business(name="Runtime Two", slug="runtime-two")
            db.add_all([first, second])
            db.flush()
            customer = Customer(
                business_id=first.id,
                channel="telegram",
                external_user_id="runtime-customer",
                name="Runtime Customer",
            )
            db.add(customer)
            db.flush()
            conversation = Conversation(
                business_id=first.id,
                customer_id=customer.id,
                channel="telegram",
            )
            db.add(conversation)
            db.commit()
            cls.business_id = first.id
            cls.other_business_id = second.id
            cls.conversation_id = conversation.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def headers(self, business_id=None):
        return {"X-Business-Id": str(business_id or self.business_id)}

    def test_config_business_hours_and_canned_response_are_tenant_scoped(self):
        updated = self.client.put(
            "/api/chatbot/config",
            headers=self.headers(),
            json={
                "name": "Owly Shop",
                "enabled": True,
                "business_hours": {"timezone": "Asia/Ho_Chi_Minh", "mon": [["08:00", "17:30"]]},
            },
        )
        self.assertEqual(200, updated.status_code)
        self.assertEqual("Owly Shop", updated.json()["name"])
        self.assertEqual("Asia/Ho_Chi_Minh", updated.json()["business_hours"]["timezone"])

        created = self.client.post(
            "/api/chatbot/canned-responses",
            headers=self.headers(),
            json={"shortcut": "/cod", "title": "COD", "content": "Shop hỗ trợ COD toàn quốc."},
        )
        self.assertEqual(201, created.status_code)
        self.assertEqual("/cod", created.json()["shortcut"])

        hidden = self.client.get(
            "/api/chatbot/canned-responses",
            headers=self.headers(self.other_business_id),
        )
        self.assertEqual(200, hidden.status_code)
        self.assertEqual([], hidden.json()["items"])

    def test_pause_and_resume_bot_is_tenant_scoped(self):
        paused = self.client.post(
            f"/api/chatbot/conversations/{self.conversation_id}/pause",
            headers=self.headers(),
            json={"reason": "Nhân viên tiếp quản"},
        )
        self.assertEqual(200, paused.status_code)
        self.assertEqual("human", paused.json()["bot_mode"])

        hidden = self.client.post(
            f"/api/chatbot/conversations/{self.conversation_id}/resume",
            headers=self.headers(self.other_business_id),
        )
        self.assertEqual(404, hidden.status_code)

        resumed = self.client.post(
            f"/api/chatbot/conversations/{self.conversation_id}/resume",
            headers=self.headers(),
        )
        self.assertEqual(200, resumed.status_code)
        self.assertEqual("auto", resumed.json()["bot_mode"])
