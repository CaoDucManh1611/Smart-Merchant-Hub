import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.customer import Customer
from app.models.crm_extended import CustomerTag, Tag


class CustomerTagsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="Tags One", slug="tags-one")
            two = Business(name="Tags Two", slug="tags-two")
            db.add_all([one, two])
            db.flush()
            customer = Customer(business_id=one.id, channel="telegram", external_user_id="tag-user")
            other = Customer(business_id=two.id, channel="telegram", external_user_id="other-user")
            db.add_all([customer, other])
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

    def test_customer_tag_can_be_added_listed_filtered_and_removed(self):
        created = self.client.post(
            f"/api/customers/{self.customer_id}/tags",
            headers={"X-Business-Id": "1"},
            json={"name": "VIP", "color": "#d33"},
        )
        self.assertEqual(201, created.status_code)
        self.assertEqual("VIP", created.json()["name"])

        profile = self.client.get(
            f"/api/customers/{self.customer_id}",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(["VIP"], profile.json()["tags"])

        filtered = self.client.get(
            "/api/customers?tag=VIP",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual([self.customer_id], [item["id"] for item in filtered.json()["items"]])

        removed = self.client.delete(
            f"/api/customers/{self.customer_id}/tags/{created.json()['id']}",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(204, removed.status_code)

        profile_after = self.client.get(
            f"/api/customers/{self.customer_id}",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual([], profile_after.json()["tags"])

        timeline = self.client.get(
            f"/api/customers/{self.customer_id}/timeline",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, timeline.status_code)
        tag_events = [item for item in timeline.json()["items"] if item["event_type"] == "customer_tag"]
        self.assertEqual({"tag_add", "tag_remove"}, {item["metadata"]["action"] for item in tag_events})

    def test_cross_tenant_customer_tag_is_rejected(self):
        response = self.client.post(
            f"/api/customers/{self.other_customer_id}/tags",
            headers={"X-Business-Id": "1"},
            json={"name": "VIP"},
        )
        self.assertEqual(404, response.status_code)

    def test_tag_ids_filter_requires_every_requested_tag(self):
        headers = {"X-Business-Id": "1"}
        vip = self.client.post(
            f"/api/customers/{self.customer_id}/tags",
            headers=headers,
            json={"name": "Segment VIP"},
        ).json()
        prospect = self.client.post(
            f"/api/customers/{self.customer_id}/tags",
            headers=headers,
            json={"name": "Segment Prospect"},
        ).json()
        response = self.client.get(
            f"/api/customers?tag_ids={vip['id']},{prospect['id']}",
            headers=headers,
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual([self.customer_id], [item["id"] for item in response.json()["items"]])

        only_vip = self.client.get(
            f"/api/customers?tag_ids={vip['id']},999999",
            headers=headers,
        )
        self.assertEqual([], only_vip.json()["items"])

    def test_tag_catalog_returns_unique_active_customer_counts(self):
        with Session(self.engine) as db:
            second_customer = Customer(
                business_id=1,
                channel="zalo",
                external_user_id="tag-user-two",
            )
            tag = Tag(business_id=1, name="Catalog Count")
            db.add_all([second_customer, tag])
            db.flush()
            db.add_all([
                CustomerTag(business_id=1, customer_id=self.customer_id, tag_id=tag.id),
                CustomerTag(business_id=1, customer_id=second_customer.id, tag_id=tag.id),
            ])
            db.commit()

        response = self.client.get(
            "/api/customers/tags/catalog",
            headers={"X-Business-Id": "1"},
        )
        self.assertEqual(200, response.status_code)
        item = next(item for item in response.json()["items"] if item["name"] == "Catalog Count")
        self.assertEqual(2, item["customer_count"])


if __name__ == "__main__":
    unittest.main()
