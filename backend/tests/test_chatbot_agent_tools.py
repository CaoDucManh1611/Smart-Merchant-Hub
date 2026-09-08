import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.business import Business
from app.models.chatbot import ChatbotConfig
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.customer_fact import CustomerFact
from app.models.message import Message
from app.models.sales import Product
from app.services.chatbot_agent import (
    build_agent_memory,
    execute_chatbot_tool,
    is_business_open,
    route_escalation,
)


class ChatbotAgentToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Tools shop", slug="tools-shop")
            db.add(business)
            db.flush()
            customer = Customer(business_id=business.id, channel="telegram", external_user_id="tools-customer", name="Lan")
            db.add(customer)
            db.flush()
            conversation = Conversation(business_id=business.id, customer_id=customer.id, channel="telegram")
            db.add(conversation)
            db.flush()
            db.add_all([
                Message(conversation_id=conversation.id, channel="telegram", direction="inbound", sender_type="customer", content="Tôi cần serum"),
                Message(conversation_id=conversation.id, channel="telegram", direction="outbound", sender_type="bot", content="Shop có serum Vitamin C"),
                CustomerFact(business_id=business.id, customer_id=customer.id, fact_type="preference", fact_key="skin_type", fact_value_json="dry"),
                Product(business_id=business.id, sku="SERUM-01", name="Serum Vitamin C", price=200000, stock_quantity=7, status="active"),
                ChatbotConfig(business_id=business.id, business_hours={"timezone": "Asia/Ho_Chi_Minh", "mon": [["08:00", "17:00"]]}),
            ])
            db.commit()
            cls.business_id, cls.customer_id, cls.conversation_id = business.id, customer.id, conversation.id

    def test_memory_contains_history_facts_and_products(self):
        with Session(self.engine) as db:
            memory = build_agent_memory(db, self.business_id, self.conversation_id)
            self.assertEqual(self.customer_id, memory["customer_id"])
            self.assertEqual(2, len(memory["history"]))
            self.assertEqual("dry", memory["facts"][0]["value"])
            self.assertEqual("Serum Vitamin C", memory["recent_products"][0]["name"])

    def test_controlled_tools_are_tenant_scoped(self):
        with Session(self.engine) as db:
            result = execute_chatbot_tool(db, self.business_id, self.conversation_id, "tim_san_pham", {"query": "serum"})
            self.assertEqual("Serum Vitamin C", result["items"][0]["name"])
            stock = execute_chatbot_tool(db, self.business_id, self.conversation_id, "xem_ton_kho", {"sku": "SERUM-01"})
            self.assertEqual(7, stock["available"])
            draft = execute_chatbot_tool(db, self.business_id, self.conversation_id, "tao_don_nhap", {"product_id": 1, "quantity": 2})
            self.assertTrue(draft["created"])
            self.assertTrue(draft["requires_confirmation"])

    def test_business_hours_and_escalation(self):
        with Session(self.engine) as db:
            self.assertTrue(is_business_open(db, self.business_id, now=datetime(2026, 9, 7, 10, 0)))
            self.assertFalse(is_business_open(db, self.business_id, now=datetime(2026, 9, 7, 19, 0)))
            ticket = route_escalation(db, self.business_id, self.conversation_id, "Tôi muốn khiếu nại hàng lỗi")
            self.assertIsNotNone(ticket)
            db.commit()
            self.assertEqual("human", db.get(Conversation, self.conversation_id).bot_mode)
