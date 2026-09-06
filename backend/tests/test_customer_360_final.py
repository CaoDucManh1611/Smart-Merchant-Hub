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
from app.models.crm_extended import CustomerTag, Tag
from app.models.audit_log import AuditLog
from app.models.customer_identity import CustomerIdentity
from app.services.customer_merge_service import duplicate_evidence


class Customer360FinalApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            one = Business(name="Final One", slug="customer-360-final-one")
            two = Business(name="Final Two", slug="customer-360-final-two")
            db.add_all([one, two])
            db.flush()

            survivor = Customer(
                business_id=one.id,
                channel="telegram",
                external_user_id="tg-survivor",
                name="Nguyen Thi An",
                email="an@example.com",
                phone="0901234567",
            )
            duplicate = Customer(
                business_id=one.id,
                channel="facebook",
                external_user_id="fb-duplicate",
                name="Nguyen Thi An",
                email="an@example.com",
                phone="0901234567",
            )
            another = Customer(
                business_id=one.id,
                channel="zalo",
                external_user_id="zalo-another",
                name="Tran Binh",
                email="binh@example.com",
                phone="0909999999",
            )
            cross_tenant = Customer(
                business_id=two.id,
                channel="telegram",
                external_user_id="tg-other",
                name="Nguyen Thi An",
                email="an@example.com",
                phone="0901234567",
            )
            db.add_all([survivor, duplicate, another, cross_tenant])
            db.flush()

            vip = Tag(business_id=one.id, name="VIP")
            paid = Tag(business_id=one.id, name="Đã mua")
            db.add_all([vip, paid])
            db.flush()
            db.add_all([
                CustomerTag(business_id=one.id, customer_id=survivor.id, tag_id=vip.id),
                CustomerTag(business_id=one.id, customer_id=survivor.id, tag_id=paid.id),
                CustomerTag(business_id=one.id, customer_id=another.id, tag_id=vip.id),
            ])

            source_conversation = Conversation(
                business_id=one.id,
                customer_id=duplicate.id,
                channel="facebook",
            )
            db.add(source_conversation)
            db.commit()

            self.business_id = one.id
            self.other_business_id = two.id
            self.survivor_id = survivor.id
            self.duplicate_id = duplicate.id
            self.another_id = another.id
            self.cross_tenant_id = cross_tenant.id
            self.source_conversation_id = source_conversation.id
            self.vip_id = vip.id
            self.paid_id = paid.id

        def override_get_db():
            with Session(self.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.engine.dispose()

    def headers(self, business_id=None):
        return {"X-Business-Id": str(business_id or self.business_id)}

    def test_duplicate_suggestions_and_preview_include_confidence_evidence(self):
        response = self.client.get(
            "/api/customers/duplicates",
            headers=self.headers(),
        )
        self.assertEqual(200, response.status_code)
        suggestions = response.json()["items"]
        self.assertEqual(1, len(suggestions))
        self.assertEqual(self.duplicate_id, suggestions[0]["source_customer_id"])
        self.assertGreaterEqual(suggestions[0]["confidence_score"], 0.9)
        self.assertIn("email", suggestions[0]["matched_fields"])
        self.assertIn("phone", suggestions[0]["matched_fields"])

        preview = self.client.post(
            f"/api/customers/{self.survivor_id}/merge-preview",
            headers=self.headers(),
            json={"source_customer_id": self.duplicate_id},
        )
        self.assertEqual(200, preview.status_code)
        body = preview.json()
        self.assertGreaterEqual(body["confidence_score"], 0.9)
        self.assertTrue(body["can_merge"])
        self.assertIn("email", body["matched_fields"])

        cross_tenant = self.client.get(
            "/api/customers/duplicates",
            headers=self.headers(self.other_business_id),
        )
        self.assertEqual(200, cross_tenant.status_code)
        self.assertEqual([], cross_tenant.json()["items"])

    def test_duplicate_evidence_considers_linked_channel_identity(self):
        with Session(self.engine) as db:
            db.add_all([
                CustomerIdentity(
                    business_id=self.business_id,
                    customer_id=self.survivor_id,
                    channel="facebook",
                    external_account_id="page-a",
                    external_user_id="shared-profile",
                ),
                CustomerIdentity(
                    business_id=self.business_id,
                    customer_id=self.another_id,
                    channel="facebook",
                    external_account_id="page-b",
                    external_user_id="shared-profile",
                ),
            ])
            db.commit()
            survivor = db.get(Customer, self.survivor_id)
            another = db.get(Customer, self.another_id)
            evidence = duplicate_evidence(db, survivor, another)
        self.assertIn("identity", evidence["matched_fields"])
        identity_evidence = next(item for item in evidence["evidence"] if item["field"] == "identity")
        self.assertEqual(1, identity_evidence["match_count"])

    def test_merge_requires_confirmation_then_history_can_undo_safely(self):
        not_confirmed = self.client.post(
            f"/api/customers/{self.survivor_id}/merge",
            headers=self.headers(),
            json={"source_customer_id": self.duplicate_id, "confirm": False},
        )
        self.assertEqual(409, not_confirmed.status_code)

        merged = self.client.post(
            f"/api/customers/{self.survivor_id}/merge",
            headers=self.headers(),
            json={"source_customer_id": self.duplicate_id, "confirm": True},
        )
        self.assertEqual(200, merged.status_code)
        merge_id = merged.json()["merge_id"]
        self.assertEqual("completed", merged.json()["status"])

        history = self.client.get(
            f"/api/customers/{self.survivor_id}/merge-history",
            headers=self.headers(),
        )
        self.assertEqual(200, history.status_code)
        self.assertEqual("completed", history.json()["items"][0]["status"])

        undone = self.client.post(
            f"/api/customers/{self.survivor_id}/merge-history/{merge_id}/undo",
            headers=self.headers(),
            json={"reason": "Xác nhận nhầm hồ sơ"},
        )
        self.assertEqual(200, undone.status_code)
        self.assertEqual("undone", undone.json()["status"])

        with Session(self.engine) as db:
            source = db.get(Customer, self.duplicate_id)
            conversation = db.get(Conversation, self.source_conversation_id)
            self.assertEqual("active", source.status)
            self.assertIsNone(source.merged_into_customer_id)
            self.assertEqual(self.duplicate_id, conversation.customer_id)

        remerged = self.client.post(
            f"/api/customers/{self.survivor_id}/merge",
            headers=self.headers(),
            json={"source_customer_id": self.duplicate_id, "confirm": True},
        )
        self.assertEqual(200, remerged.status_code)
        self.assertNotEqual(merge_id, remerged.json()["merge_id"])
        self.assertEqual("completed", remerged.json()["status"])

        history_after_remerge = self.client.get(
            f"/api/customers/{self.survivor_id}/merge-history",
            headers=self.headers(),
        )
        self.assertEqual(2, history_after_remerge.json()["total"])
        self.assertEqual("completed", history_after_remerge.json()["items"][0]["status"])
        self.assertEqual("undone", history_after_remerge.json()["items"][1]["status"])

    def test_undo_is_rejected_when_survivor_changed_after_merge(self):
        merged = self.client.post(
            f"/api/customers/{self.survivor_id}/merge",
            headers=self.headers(),
            json={"source_customer_id": self.duplicate_id, "confirm": True},
        )
        self.assertEqual(200, merged.status_code)
        merge_id = merged.json()["merge_id"]

        with Session(self.engine) as db:
            db.add(Conversation(
                business_id=self.business_id,
                customer_id=self.survivor_id,
                channel="telegram",
            ))
            db.commit()

        undone = self.client.post(
            f"/api/customers/{self.survivor_id}/merge-history/{merge_id}/undo",
            headers=self.headers(),
            json={"reason": "Không được tách khi đã có dữ liệu mới"},
        )
        self.assertEqual(409, undone.status_code)

    def test_undo_merge_is_visible_in_customer_timeline(self):
        merged = self.client.post(
            f"/api/customers/{self.survivor_id}/merge",
            headers=self.headers(),
            json={"source_customer_id": self.duplicate_id, "confirm": True},
        )
        self.assertEqual(200, merged.status_code)
        merge_id = merged.json()["merge_id"]

        undone = self.client.post(
            f"/api/customers/{self.survivor_id}/merge-history/{merge_id}/undo",
            headers=self.headers(),
            json={"reason": "Tách lại hồ sơ"},
        )
        self.assertEqual(200, undone.status_code)

        timeline = self.client.get(
            f"/api/customers/{self.survivor_id}/timeline",
            headers=self.headers(),
        )
        self.assertEqual(200, timeline.status_code)
        undo_events = [
            item for item in timeline.json()["items"]
            if item["event_type"] == "customer_merge_undo"
        ]
        self.assertEqual(1, len(undo_events))
        self.assertEqual("Tách lại hồ sơ", undo_events[0]["content"])

    def test_saved_segment_matches_multiple_tags_and_is_tenant_scoped(self):
        created = self.client.post(
            "/api/customers/segments",
            headers=self.headers(),
            json={
                "name": "VIP đã mua",
                "description": "Khách VIP đã có đơn",
                "tag_ids": [self.vip_id, self.paid_id],
                "match_mode": "all",
            },
        )
        self.assertEqual(201, created.status_code)
        segment = created.json()
        self.assertEqual([self.vip_id, self.paid_id], segment["tag_ids"])

        members = self.client.get(
            f"/api/customers/segments/{segment['id']}/customers",
            headers=self.headers(),
        )
        self.assertEqual(200, members.status_code)
        self.assertEqual([self.survivor_id], [item["id"] for item in members.json()["items"]])

        other_tenant = self.client.get(
            "/api/customers/segments",
            headers=self.headers(self.other_business_id),
        )
        self.assertEqual(200, other_tenant.status_code)
        self.assertEqual([], other_tenant.json()["items"])

    def test_segment_rejects_tag_from_another_tenant(self):
        response = self.client.post(
            "/api/customers/segments",
            headers=self.headers(),
            json={"name": "Không hợp lệ", "tag_ids": [999999], "match_mode": "all"},
        )
        self.assertEqual(422, response.status_code)

    def test_customer_fact_and_segment_writes_are_audited_without_sensitive_values(self):
        fact = self.client.post(
            f"/api/customers/{self.survivor_id}/facts",
            headers=self.headers(),
            json={
                "fact_type": "preference",
                "fact_key": "budget_max",
                "fact_value": 500000,
                "confidence": 0.95,
                "source_type": "manual",
                "is_verified": True,
            },
        )
        self.assertEqual(201, fact.status_code, fact.text)
        fact_id = fact.json()["id"]
        updated_fact = self.client.patch(
            f"/api/customers/{self.survivor_id}/facts/{fact_id}",
            headers=self.headers(),
            json={"is_verified": False},
        )
        self.assertEqual(200, updated_fact.status_code, updated_fact.text)
        deleted_fact = self.client.delete(
            f"/api/customers/{self.survivor_id}/facts/{fact_id}",
            headers=self.headers(),
        )
        self.assertEqual(204, deleted_fact.status_code, deleted_fact.text)

        segment = self.client.post(
            "/api/customers/segments",
            headers=self.headers(),
            json={"name": "Audit segment", "tag_ids": [self.vip_id]},
        )
        self.assertEqual(201, segment.status_code, segment.text)
        segment_id = segment.json()["id"]
        updated_segment = self.client.patch(
            f"/api/customers/segments/{segment_id}",
            headers=self.headers(),
            json={"match_mode": "any"},
        )
        self.assertEqual(200, updated_segment.status_code, updated_segment.text)
        deleted_segment = self.client.delete(
            f"/api/customers/segments/{segment_id}",
            headers=self.headers(),
        )
        self.assertEqual(204, deleted_segment.status_code, deleted_segment.text)

        with Session(self.engine) as db:
            actions = {
                row.action
                for row in db.query(AuditLog).filter(AuditLog.business_id == self.business_id).all()
            }
            self.assertTrue({"fact_create", "fact_update", "fact_delete", "segment_create", "segment_update", "segment_delete"}.issubset(actions))
            self.assertTrue(all("fact_value" not in (row.metadata_ or {}) for row in db.query(AuditLog).all()))

    def test_customer_list_supports_all_and_any_multi_tag_filters(self):
        all_tags = self.client.get(
            f"/api/customers?tag_ids={self.vip_id},{self.paid_id}&match_mode=all",
            headers=self.headers(),
        )
        self.assertEqual(200, all_tags.status_code)
        self.assertEqual([self.survivor_id], [item["id"] for item in all_tags.json()["items"]])

        any_tag = self.client.get(
            f"/api/customers?tag_ids={self.vip_id},{self.paid_id}&match_mode=any",
            headers=self.headers(),
        )
        self.assertEqual(200, any_tag.status_code)
        self.assertEqual(
            {self.survivor_id, self.another_id},
            {item["id"] for item in any_tag.json()["items"]},
        )


if __name__ == "__main__":
    unittest.main()
