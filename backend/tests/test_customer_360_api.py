import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.customer_identity import CustomerIdentity
from app.models.customer_fact import CustomerFact
from app.models.message import Message
from app.models.crm_extended import ConversationAssignment, ConversationTag, Tag
from app.models.lead import Lead
from app.models.sales import Order
from app.models.ticket import Ticket, TicketComment, TicketEvent
from app.models.business import User
from app.models.audit_log import AuditLog


class Customer360ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="One", slug="customer-360-one")
            two = Business(name="Two", slug="customer-360-two")
            db.add_all([one, two])
            db.flush()
            customer = Customer(
                business_id=one.id,
                channel="telegram",
                external_user_id="tg-1",
                name="Nguyen Van A",
                phone="0900000001",
            )
            db.add(customer)
            db.flush()
            db.add(CustomerIdentity(
                business_id=one.id,
                customer_id=customer.id,
                channel="telegram",
                external_account_id="bot-1",
                external_user_id="tg-1",
                display_name="Nguyen Van A",
            ))
            conversation = Conversation(
                business_id=one.id,
                customer_id=customer.id,
                channel="telegram",
            )
            db.add(conversation)
            db.flush()
            db.add(Message(
                conversation_id=conversation.id,
                channel="telegram",
                external_user_id="tg-1",
                content="Tôi cần mua hàng",
                direction="inbound",
                received_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ))
            db.flush()
            vip = Tag(business_id=one.id, name="VIP")
            db.add(vip)
            db.flush()
            db.add(ConversationTag(conversation_id=conversation.id, tag_id=vip.id))
            other = Customer(
                business_id=two.id,
                channel="facebook",
                external_user_id="fb-2",
                name="Tenant B",
            )
            db.add(other)
            db.commit()
            cls.customer_id = customer.id
            cls.other_customer_id = other.id

        def override_get_db():
            with Session(cls.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()

    def test_customer_list_is_tenant_scoped(self):
        response = self.client.get("/api/customers", headers={"X-Business-Id": "1"})
        self.assertEqual(200, response.status_code)
        self.assertEqual([self.customer_id], [item["id"] for item in response.json()["items"]])

    def test_customer_profile_contains_identities_and_conversation_summary(self):
        response = self.client.get(
            f"/api/customers/{self.customer_id}",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("Nguyen Van A", body["name"])
        self.assertEqual(1, len(body["identities"]))
        self.assertEqual(1, body["conversation_count"])

    def test_customer_profile_contains_real_conversation_tags(self):
        response = self.client.get(
            f"/api/customers/{self.customer_id}",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual(["VIP"], response.json()["tags"])

    def test_cross_tenant_customer_returns_404(self):
        response = self.client.get(
            f"/api/customers/{self.other_customer_id}",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(404, response.status_code)

    def test_timeline_contains_message_and_internal_note(self):
        response = self.client.get(
            f"/api/customers/{self.customer_id}/timeline",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("message", response.json()["items"][0]["event_type"])

        note = self.client.post(
            f"/api/customers/{self.customer_id}/notes",
            headers={"X-Business-Id": "1"},
            json={"content": "Khách quan tâm sản phẩm mới"},
        )
        self.assertEqual(201, note.status_code)
        with Session(self.engine) as db:
            self.assertIsNotNone(db.query(AuditLog).filter(
                AuditLog.business_id == 1,
                AuditLog.action == "note_create",
                AuditLog.resource_type == "customer_note",
                AuditLog.resource_id == str(note.json()["id"]),
            ).first())
        timeline = self.client.get(
            f"/api/customers/{self.customer_id}/timeline",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, timeline.status_code)
        self.assertIn("note", {item["event_type"] for item in timeline.json()["items"]})

    def test_timeline_identifies_customer_bot_and_staff_actors(self):
        """Catch outbound timeline rows being shown as anonymous customer messages."""
        with Session(self.engine) as db:
            conversation = db.query(Conversation).filter(
                Conversation.customer_id == self.customer_id,
                Conversation.business_id == 1,
            ).first()
            staff = User(
                business_id=1,
                full_name="Linh tư vấn",
                email="linh-actor@example.com",
            )
            db.add(staff)
            db.flush()
            db.add_all([
                Message(
                    conversation_id=conversation.id,
                    channel="telegram",
                    direction="inbound",
                    sender_type="customer",
                    content="actor-customer",
                ),
                Message(
                    conversation_id=conversation.id,
                    channel="telegram",
                    direction="outbound",
                    sender_type="bot",
                    content="actor-bot",
                    auto_reply_key="inbound:1:1:700:rag",
                    metadata_={
                        "correlation_id": "inbound:1:1:700:rag",
                        "inbound_message_id": "700",
                        "route": "rag",
                    },
                ),
                Message(
                    conversation_id=conversation.id,
                    channel="telegram",
                    direction="outbound",
                    sender_type="customer",
                    content="actor-legacy-bot",
                ),
                Message(
                    conversation_id=conversation.id,
                    channel="telegram",
                    direction="outbound",
                    sender_type="staff",
                    sender_user_id=staff.id,
                    content="actor-staff",
                ),
            ])
            db.commit()

        response = self.client.get(
            f"/api/customers/{self.customer_id}/timeline",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, response.status_code)
        messages = {
            item["content"]: item
            for item in response.json()["items"]
            if item["event_type"] == "message" and item["content"].startswith("actor-")
        }
        self.assertEqual("customer", messages["actor-customer"]["actor_type"])
        self.assertEqual("bot", messages["actor-bot"]["actor_type"])
        self.assertEqual("700", messages["actor-bot"]["metadata"]["inbound_message_id"])
        self.assertEqual("rag", messages["actor-bot"]["metadata"]["route"])
        self.assertEqual("bot", messages["actor-legacy-bot"]["actor_type"])
        self.assertEqual("staff", messages["actor-staff"]["actor_type"])
        self.assertEqual("Linh tư vấn", messages["actor-staff"]["actor_name"])

    def test_timeline_includes_crm_events_with_metadata(self):
        with Session(self.engine) as db:
            conversation = db.query(Conversation).filter(Conversation.customer_id == self.customer_id).first()
            user = User(
                business_id=1,
                full_name="Agent",
                email="timeline-agent@example.com",
            )
            db.add(user)
            db.flush()
            lead = Lead(
                business_id=1,
                customer_id=self.customer_id,
                conversation_id=conversation.id,
                title="Cơ hội serum",
                stage="qualified",
            )
            order = Order(
                business_id=1,
                customer_id=self.customer_id,
                conversation_id=conversation.id,
                order_number="TL-001",
                status="confirmed",
            )
            ticket = Ticket(
                business_id=1,
                customer_id=self.customer_id,
                conversation_id=conversation.id,
                title="Cần hỗ trợ giao hàng",
            )
            db.add_all([lead, order, ticket])
            db.flush()
            db.add(TicketComment(
                business_id=1,
                ticket_id=ticket.id,
                body="Đã kiểm tra đơn",
                author_user_id=user.id,
            ))
            db.add(ConversationAssignment(
                conversation_id=conversation.id,
                user_id=user.id,
                assignment_type="manual",
            ))
            db.commit()

        response = self.client.get(
            f"/api/customers/{self.customer_id}/timeline",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, response.status_code)
        event_types = {item["event_type"] for item in response.json()["items"]}
        self.assertTrue({"lead", "sales_order", "ticket", "ticket_comment", "assignment"}.issubset(event_types))
        self.assertIn("metadata", response.json()["items"][0])

    def test_timeline_supports_offset_pagination_and_reports_remaining_items(self):
        with Session(self.engine) as db:
            db.add_all([
                AuditLog(
                    business_id=1,
                    action="profile_update",
                    resource_type="customer",
                    resource_id=str(self.customer_id),
                    metadata_={"field": "phone"},
                ),
                AuditLog(
                    business_id=1,
                    action="merge_undo",
                    resource_type="customer",
                    resource_id=str(self.customer_id),
                    metadata_={"merge_id": 17, "reason": "Tách hồ sơ"},
                ),
            ])
            db.commit()

        first_page = self.client.get(
            f"/api/customers/{self.customer_id}/timeline?limit=1&offset=0",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, first_page.status_code)
        first_body = first_page.json()
        self.assertEqual(1, len(first_body["items"]))
        self.assertGreaterEqual(first_body["total"], 3)
        self.assertTrue(first_body["has_more"])
        self.assertEqual(1, first_body["next_offset"])

        second_page = self.client.get(
            f"/api/customers/{self.customer_id}/timeline?limit=100&offset=0",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, second_page.status_code)
        event_types = {item["event_type"] for item in second_page.json()["items"]}
        self.assertIn("customer_merge_undo", event_types)

    def test_timeline_date_and_staff_filters_keep_selected_staff_scope(self):
        """A selected staff member must never pull in other actors' events."""
        with Session(self.engine) as db:
            conversation = db.query(Conversation).filter(
                Conversation.customer_id == self.customer_id,
                Conversation.business_id == 1,
            ).first()
            staff = User(
                business_id=1,
                full_name="Timeline Filter Staff",
                email="timeline-filter-staff@example.com",
            )
            db.add(staff)
            db.flush()
            staff_id = staff.id
            db.add_all([
                Message(
                    conversation_id=conversation.id,
                    channel="telegram",
                    sender_type="staff",
                    sender_user_id=staff.id,
                    content="all-match-2030",
                    direction="outbound",
                    received_at=datetime(2030, 1, 10, 10, 0),
                ),
                Message(
                    conversation_id=conversation.id,
                    channel="telegram",
                    sender_type="staff",
                    sender_user_id=staff.id,
                    content="staff-outside-date-2030",
                    direction="outbound",
                    received_at=datetime(2030, 1, 11, 10, 0),
                ),
                Message(
                    conversation_id=conversation.id,
                    channel="telegram",
                    sender_type="customer",
                    content="date-other-actor-2030",
                    direction="inbound",
                    received_at=datetime(2030, 1, 10, 11, 0),
                ),
            ])
            db.commit()

        common_query = (
            f"/api/customers/{self.customer_id}/timeline?start_date=2030-01-10"
            f"&end_date=2030-01-10&staff_id={staff_id}"
        )
        combined_response = self.client.get(
            common_query,
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, combined_response.status_code)
        combined_contents = {item["content"] for item in combined_response.json()["items"]}
        self.assertIn("all-match-2030", combined_contents)
        self.assertNotIn("staff-outside-date-2030", combined_contents)
        self.assertNotIn("date-other-actor-2030", combined_contents)

        staff_only_response = self.client.get(
            f"/api/customers/{self.customer_id}/timeline?staff_id={staff_id}",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, staff_only_response.status_code)
        staff_only_contents = {item["content"] for item in staff_only_response.json()["items"]}
        self.assertTrue({"all-match-2030", "staff-outside-date-2030"}.issubset(staff_only_contents))
        self.assertNotIn("date-other-actor-2030", staff_only_contents)

        date_only_response = self.client.get(
            f"/api/customers/{self.customer_id}/timeline?start_date=2030-01-10&end_date=2030-01-10",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, date_only_response.status_code)
        date_only_contents = {item["content"] for item in date_only_response.json()["items"]}
        self.assertTrue({"all-match-2030", "date-other-actor-2030"}.issubset(date_only_contents))
        self.assertNotIn("staff-outside-date-2030", date_only_contents)

    def test_message_search_returns_ten_customer_scoped_results_per_page(self):
        with Session(self.engine) as db:
            conversation = db.query(Conversation).filter(
                Conversation.customer_id == self.customer_id,
                Conversation.business_id == 1,
            ).first()
            conversation_id = conversation.id
            db.add_all([
                Message(
                    conversation_id=conversation_id,
                    channel="telegram",
                    sender_type="customer",
                    direction="inbound",
                    content=f"customer-search-needle-{index}",
                    received_at=datetime(2031, 2, 1, 9, index),
                )
                for index in range(12)
            ])
            db.commit()

        first_page = self.client.get(
            f"/api/customers/{self.customer_id}/message-search?q=customer-search-needle&limit=10",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, first_page.status_code)
        first_body = first_page.json()
        self.assertEqual(12, first_body["total"])
        self.assertEqual(10, len(first_body["items"]))
        self.assertTrue(first_body["has_more"])
        self.assertEqual(10, first_body["next_offset"])
        self.assertTrue(all(item["conversation_id"] == conversation_id for item in first_body["items"]))

        second_page = self.client.get(
            f"/api/customers/{self.customer_id}/message-search?q=customer-search-needle&limit=10&offset=10",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, second_page.status_code)
        second_body = second_page.json()
        self.assertEqual(2, len(second_body["items"]))
        self.assertFalse(second_body["has_more"])

    def test_timeline_includes_identity_fact_and_ticket_history_events(self):
        with Session(self.engine) as db:
            conversation = db.query(Conversation).filter(
                Conversation.customer_id == self.customer_id,
                Conversation.business_id == 1,
            ).first()
            db.add(CustomerIdentity(
                business_id=1,
                customer_id=self.customer_id,
                channel="facebook",
                external_account_id="page-1",
                external_user_id="fb-360",
                username="customer360",
            ))
            fact = CustomerFact(
                business_id=1,
                customer_id=self.customer_id,
                fact_type="preference",
                fact_key="budget_max",
                fact_value_json=500000,
                confidence=0.95,
                source_type="manual",
                is_verified=True,
            )
            ticket = Ticket(
                business_id=1,
                customer_id=self.customer_id,
                conversation_id=conversation.id,
                title="Theo dõi yêu cầu",
                status="pending",
            )
            db.add_all([fact, ticket])
            db.flush()
            db.add(TicketEvent(
                business_id=1,
                ticket_id=ticket.id,
                event_type="status_changed",
                from_value="open",
                to_value="pending",
            ))
            ticket_id = ticket.id
            db.commit()

        response = self.client.get(
            f"/api/customers/{self.customer_id}/timeline",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, response.status_code, response.text)
        items = response.json()["items"]
        event_types = {item["event_type"] for item in items}
        self.assertTrue({"identity", "fact", "ticket_event"}.issubset(event_types))
        fact_event = next(item for item in items if item["event_type"] == "fact")
        self.assertEqual("budget_max", fact_event["metadata"]["fact_key"])
        self.assertEqual(500000, fact_event["metadata"]["fact_value"])
        ticket_event = next(item for item in items if item["event_type"] == "ticket_event")
        self.assertEqual(ticket_id, ticket_event["metadata"]["ticket_id"])
        self.assertEqual("open", ticket_event["metadata"]["from_value"])


if __name__ == "__main__":
    unittest.main()
