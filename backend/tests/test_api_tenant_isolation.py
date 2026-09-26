import unittest

from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.bases import TenantBase
from app.main import app
from app.models.audit_log import AuditLog
from app.models.customer import Customer
from app.models.conversation import Conversation
from app.models.crm_extended import ConversationAssignment
from app.models.message import Message
from app.models.business import Business, User
from app.models.permission import PermissionOverride
from app.database.platform_session import get_platform_db
from app.db.dependencies import get_db
from app.auth.dependencies import require_write_access
from app.tenancy.context import TenantContext
from app.tenancy.crm_session import get_tenant_db
from app.tenancy.dependencies import get_tenant_context


class ApiTenantIsolationTests(unittest.TestCase):
    """CRM routes must obtain data from the authenticated shop session."""

    @classmethod
    def setUpClass(cls):
        cls.engines = {
            business_id: create_engine(
                "sqlite://", poolclass=StaticPool,
                connect_args={"check_same_thread": False},
            ) for business_id in (1, 2)
        }
        for business_id, engine in cls.engines.items():
            TenantBase.metadata.create_all(engine)
            with Session(engine) as db:
                # IDs and provider identities intentionally collide across
                # schemas. The bound database, not a WHERE clause, isolates.
                db.add(Customer(
                    id=1,
                    business_id=business_id,
                    channel="facebook",
                    external_user_id="shared-external-id",
                    name=f"Shop {business_id} customer",
                ))
                db.add(Conversation(id=1, business_id=business_id, customer_id=1, channel="facebook"))
                db.add(Message(id=1, conversation_id=1, channel="facebook", content=f"Shop {business_id} message"))
                db.add(PermissionOverride(id=1, business_id=business_id, resource="customers", action="write", role="agent", effect="allow" if business_id == 1 else "deny"))
                db.commit()

        def override_tenant_context(request: Request) -> TenantContext:
            return TenantContext(int(request.headers["X-Business-Id"]), "test")

        def override_tenant_db(request: Request):
            with Session(cls.engines[int(request.headers["X-Business-Id"])]) as db:
                yield db

        app.dependency_overrides[get_tenant_context] = override_tenant_context
        app.dependency_overrides[get_tenant_db] = override_tenant_db
        app.dependency_overrides[require_write_access] = lambda: None
        cls.platform_engine = create_engine(
            "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False},
        )
        Business.__table__.create(cls.platform_engine)
        User.__table__.create(cls.platform_engine)
        with cls.platform_engine.begin() as connection:
            connection.execute(Business.__table__.insert(), [{"id": 1, "name": "One", "slug": "one"}, {"id": 2, "name": "Two", "slug": "two"}])
            connection.execute(User.__table__.insert(), [
                {"id": 101, "business_id": 1, "full_name": "Shop one agent", "email": "one@example.test", "role": "agent", "is_active": True},
                {"id": 201, "business_id": 2, "full_name": "Other shop agent", "email": "other@example.test", "role": "agent", "is_active": True},
            ])

        def override_platform_db():
            with Session(cls.platform_engine) as db:
                yield db

        app.dependency_overrides[get_platform_db] = override_platform_db
        app.dependency_overrides[get_db] = override_platform_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        for engine in cls.engines.values():
            engine.dispose()
        cls.platform_engine.dispose()

    def test_identical_customer_ids_are_read_from_the_authenticated_shop_session(self):
        one = self.client.get("/api/customers", headers={"X-Business-Id": "1"})
        two = self.client.get("/api/customers", headers={"X-Business-Id": "2"})

        self.assertEqual(200, one.status_code)
        self.assertEqual(200, two.status_code)
        self.assertEqual("Shop 1 customer", one.json()["items"][0]["name"])
        self.assertEqual("Shop 2 customer", two.json()["items"][0]["name"])

    def test_identical_conversation_ids_read_only_shop_messages(self):
        for business_id in (1, 2):
            response = self.client.get(
                "/api/conversations/1/messages", headers={"X-Business-Id": str(business_id)},
            )
            self.assertEqual(200, response.status_code, response.text)
            self.assertIn(f"Shop {business_id} message", response.text)
            self.assertNotIn(f"Shop {3 - business_id} message", response.text)

    def test_unassignment_changes_only_authenticated_shop_conversation(self):
        for business_id, engine in self.engines.items():
            with Session(engine) as db:
                db.get(Conversation, 1).assigned_user_id = 101
                db.commit()
        response = self.client.patch(
            "/api/conversations/1/assignment", json={"assigned_user_id": None},
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, response.status_code, response.text)
        with Session(self.engines[1]) as first, Session(self.engines[2]) as second:
            self.assertIsNone(first.get(Conversation, 1).assigned_user_id)
            self.assertEqual(101, second.get(Conversation, 1).assigned_user_id)

    def test_assignment_rejects_platform_user_from_another_shop(self):
        response = self.client.patch(
            "/api/conversations/1/assignment", json={"assigned_user_id": 201},
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(404, response.status_code, response.text)

    def test_bulk_assignment_is_tenant_scoped_atomic_and_audited(self):
        success = self.client.patch(
            "/api/conversations/bulk-assignment",
            json={"conversation_ids": [1], "assigned_user_id": 101},
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, success.status_code, success.text)
        self.assertEqual(1, success.json()["changed_count"])
        with Session(self.engines[1]) as db:
            conversation = db.get(Conversation, 1)
            self.assertEqual(101, conversation.assigned_user_id)
            self.assertEqual(101, db.query(ConversationAssignment).filter_by(conversation_id=1, unassigned_at=None).one().user_id)
            audit = db.query(AuditLog).filter_by(action="conversation_assignment", resource_id="1").one()
            self.assertTrue(audit.metadata_["bulk"])

        # Conversation 2 exists only in shop 2. The mixed request must not
        # partially reassign conversation 1 in shop 1.
        with Session(self.engines[2]) as db:
            db.add(Conversation(id=2, business_id=2, customer_id=1, channel="facebook"))
            db.commit()
        rejected = self.client.patch(
            "/api/conversations/bulk-assignment",
            json={"conversation_ids": [1, 2], "assigned_user_id": None},
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(404, rejected.status_code, rejected.text)
        with Session(self.engines[1]) as db:
            self.assertEqual(101, db.get(Conversation, 1).assigned_user_id)

        duplicate = self.client.patch(
            "/api/conversations/bulk-assignment",
            json={"conversation_ids": [1, 1], "assigned_user_id": 101},
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(422, duplicate.status_code, duplicate.text)

    def test_conversation_outcome_is_validated_audited_and_tenant_scoped(self):
        for business_id, outcome in ((1, "resolved"), (2, "needs_human")):
            response = self.client.patch(
                "/api/conversations/1/outcome",
                json={"outcome": outcome},
                headers={"X-Business-Id": str(business_id)},
            )
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual(outcome, response.json()["resolution_outcome"])

        invalid = self.client.patch(
            "/api/conversations/1/outcome",
            json={"outcome": "probably_resolved"},
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(422, invalid.status_code, invalid.text)

        for business_id, expected in ((1, "resolved"), (2, "needs_human")):
            with Session(self.engines[business_id]) as db:
                self.assertEqual(expected, db.get(Conversation, 1).resolution_outcome)
                audit = db.query(AuditLog).filter_by(
                    business_id=business_id,
                    action="conversation_outcome_recorded",
                    resource_id="1",
                ).one()
                self.assertEqual(expected, audit.metadata_["to"])

            listing = self.client.get(
                "/api/conversations?limit=10",
                headers={"X-Business-Id": str(business_id)},
            )
            row = next(item for item in listing.json()["items"] if item["conversation_id"] == 1)
            self.assertEqual(expected, row["resolution_outcome"])

    def test_team_permission_overrides_with_identical_ids_are_shop_local(self):
        for business_id, effect in ((1, "allow"), (2, "deny")):
            response = self.client.get("/api/team/permissions", headers={"X-Business-Id": str(business_id)})
            self.assertEqual(200, response.status_code, response.text)
            self.assertEqual(effect, response.json()["items"][0]["effect"])


if __name__ == "__main__":
    unittest.main()
