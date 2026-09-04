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
from app.models.customer_note import CustomerNote
from app.models.crm_extended import CustomerTag, Tag
from app.models.message import Message
from app.models.purchase_order import PurchaseOrder


class CustomerMergeApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="Merge One", slug="merge-one")
            two = Business(name="Merge Two", slug="merge-two")
            db.add_all([one, two])
            db.flush()
            survivor = Customer(
                business_id=one.id,
                channel="telegram",
                external_user_id="survivor",
                name="Khách chính",
            )
            source = Customer(
                business_id=one.id,
                channel="facebook",
                external_user_id="source",
                name="Khách trùng",
            )
            other = Customer(
                business_id=two.id,
                channel="telegram",
                external_user_id="other",
                name="Tenant khác",
            )
            db.add_all([survivor, source, other])
            db.flush()
            identity = CustomerIdentity(
                business_id=one.id,
                customer_id=source.id,
                channel="instagram",
                external_account_id="ig-page",
                external_user_id="source-ig",
                display_name="Khách trùng IG",
            )
            conversation = Conversation(
                business_id=one.id,
                customer_id=source.id,
                channel="facebook",
            )
            note = CustomerNote(
                business_id=one.id,
                customer_id=source.id,
                content="Ghi chú từ hồ sơ trùng",
            )
            tag = Tag(business_id=one.id, name="VIP")
            db.add_all([identity, conversation, note, tag])
            db.flush()
            db.add(CustomerTag(
                business_id=one.id,
                customer_id=source.id,
                tag_id=tag.id,
            ))
            db.add(Message(
                conversation_id=conversation.id,
                channel="facebook",
                external_user_id="source",
                content="Tin từ hồ sơ trùng",
                direction="inbound",
                received_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ))
            db.add(PurchaseOrder(
                business_id=one.id,
                po_number="PO-MERGE-1",
                supplier_name="Nhà cung cấp",
                metadata_={"customer_id": source.id},
            ))
            db.commit()
            cls.business_id = one.id
            cls.other_business_id = two.id
            cls.survivor_id = survivor.id
            cls.source_id = source.id
            cls.other_customer_id = other.id
            cls.conversation_id = conversation.id
            cls.identity_id = identity.id

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

    def test_merge_preview_reports_source_records(self):
        response = self.client.post(
            f"/api/customers/{self.survivor_id}/merge-preview",
            headers=self.headers(),
            json={"source_customer_id": self.source_id},
        )
        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual(self.survivor_id, body["survivor_customer_id"])
        self.assertEqual(self.source_id, body["source_customer_id"])
        self.assertEqual(1, body["source_counts"]["identities"])
        self.assertEqual(1, body["source_counts"]["conversations"])
        self.assertEqual(1, body["source_counts"]["notes"])
        self.assertEqual(1, body["source_counts"]["tags"])
        self.assertEqual(1, body["source_counts"]["purchase_orders"])

    def test_merge_reassigns_dependencies_and_deactivates_source(self):
        response = self.client.post(
            f"/api/customers/{self.survivor_id}/merge",
            headers=self.headers(),
            json={"source_customer_id": self.source_id, "reason": "Gộp hồ sơ trùng"},
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("completed", response.json()["status"])

        with Session(self.engine) as db:
            source = db.get(Customer, self.source_id)
            self.assertEqual("merged", source.status)
            self.assertEqual(self.survivor_id, source.merged_into_customer_id)
            self.assertEqual(self.survivor_id, db.get(Conversation, self.conversation_id).customer_id)
            self.assertEqual(self.survivor_id, db.get(CustomerIdentity, self.identity_id).customer_id)
            self.assertEqual(
                1,
                db.query(CustomerNote).filter(CustomerNote.customer_id == self.survivor_id).count(),
            )
            self.assertEqual(
                1,
                db.query(CustomerTag).filter(CustomerTag.customer_id == self.survivor_id).count(),
            )
            purchase = db.query(PurchaseOrder).filter(PurchaseOrder.po_number == "PO-MERGE-1").one()
            self.assertEqual(self.survivor_id, purchase.metadata_["customer_id"])

    def test_duplicate_merge_is_rejected(self):
        with Session(self.engine) as db:
            fresh_source = Customer(
                business_id=self.business_id,
                channel="zalo",
                external_user_id="duplicate-source",
                name="Hồ sơ lặp",
            )
            db.add(fresh_source)
            db.commit()
            fresh_source_id = fresh_source.id

        response = self.client.post(
            f"/api/customers/{self.survivor_id}/merge",
            headers=self.headers(),
            json={"source_customer_id": fresh_source_id},
        )
        self.assertEqual(200, response.status_code)
        response = self.client.post(
            f"/api/customers/{self.survivor_id}/merge",
            headers=self.headers(),
            json={"source_customer_id": fresh_source_id},
        )
        self.assertEqual(409, response.status_code)

    def test_cross_tenant_merge_is_not_visible(self):
        response = self.client.post(
            f"/api/customers/{self.survivor_id}/merge-preview",
            headers=self.headers(),
            json={"source_customer_id": self.other_customer_id},
        )
        self.assertEqual(404, response.status_code)


if __name__ == "__main__":
    unittest.main()
