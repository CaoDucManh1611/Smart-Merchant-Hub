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
from app.models.message import Message


class TopicDiscoveryApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            first = Business(name="Topic One", slug="topic-one")
            second = Business(name="Topic Two", slug="topic-two")
            db.add_all([first, second])
            db.flush()
            for business, external_id, contents in (
                (first, "first", ["Shop có giao hàng không?", "Phí giao hàng bao nhiêu?"]),
                (second, "second", ["Khiếu nại bí mật tenant hai", "Hỗ trợ khiếu nại tenant hai"]),
            ):
                customer = Customer(
                    business_id=business.id,
                    channel="telegram",
                    external_user_id=external_id,
                    name=external_id,
                )
                db.add(customer)
                db.flush()
                conversation = Conversation(
                    business_id=business.id,
                    customer_id=customer.id,
                    channel="telegram",
                )
                db.add(conversation)
                db.flush()
                db.add_all([
                    Message(
                        conversation_id=conversation.id,
                        channel="telegram",
                        direction="inbound",
                        content=content,
                    )
                    for content in contents
                ])
            db.commit()
            cls.business_id = first.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()

    def test_endpoint_is_tenant_scoped_and_never_updates_knowledge_base(self):
        response = self.client.get(
            "/api/chatbot/learning/topic-suggestions",
            headers={"X-Business-Id": str(self.business_id)},
        )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(2, payload["messages_analyzed"])
        self.assertFalse(payload["knowledge_base_updated"])
        self.assertTrue(payload["suggestions"])
        serialized = str(payload)
        self.assertNotIn("tenant hai", serialized)
        self.assertTrue(all(item["review_status"] == "pending_review" for item in payload["suggestions"]))


if __name__ == "__main__":
    unittest.main()
