import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.customer import Customer
from app.models.recommendation import (
    CustomerProductInteraction,
    RecommendationCustomerProfile,
    RecommendationTrainingRun,
)
from app.models.sales import Order, OrderItem, Product
from app.services.crm_job_worker import dispatch_business_crm_jobs
from app.services.order_service import transition_sales_order
from app.services.recommendation_interaction_service import record_order_purchase_interactions


class RecommendationApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            business = Business(name="Recommendations", slug="recommendations")
            other_business = Business(name="Other tenant", slug="other-tenant")
            db.add_all([business, other_business])
            db.flush()
            cls.business_id = business.id
            cls.other_business_id = other_business.id

            customer = Customer(business_id=business.id, channel="telegram", external_user_id="recommendation-customer")
            second_customer = Customer(business_id=business.id, channel="telegram", external_user_id="recommendation-customer-2")
            db.add_all([customer, second_customer])
            db.flush()
            cls.customer_id = customer.id

            products = [
                Product(business_id=business.id, sku="P-ONE", name="Product one", price=Decimal("10"), stock_quantity=5),
                Product(business_id=business.id, sku="P-TWO", name="Product two", price=Decimal("20"), stock_quantity=5),
                Product(business_id=business.id, sku="P-THREE", name="Product three", price=Decimal("30"), stock_quantity=5),
                Product(business_id=business.id, sku="P-OOS", name="Out of stock", price=Decimal("40"), stock_quantity=0),
            ]
            db.add_all(products)
            db.flush()
            cls.product_ids = [product.id for product in products]

            for index, (buyer_id, item_ids) in enumerate(((customer.id, products[:2]), (second_customer.id, products[1:3])), start=1):
                order = Order(
                    business_id=business.id,
                    customer_id=buyer_id,
                    order_number=f"REC-{index}",
                    status="completed",
                    total_amount=sum((item.price for item in item_ids), Decimal("0")),
                    created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=index),
                )
                db.add(order)
                db.flush()
                for product in item_ids:
                    db.add(OrderItem(
                        order_id=order.id,
                        product_id=product.id,
                        quantity=1,
                        unit_price=product.price,
                        line_total=product.price,
                        product_name_snapshot=product.name,
                        sku_snapshot=product.sku,
                    ))
            db.commit()

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

    def test_serves_tenant_scoped_recommendations_and_records_idempotent_feedback(self):
        response = self.client.post(
            "/api/recommendations",
            headers=self.headers(),
            json={
                "customer_id": self.customer_id,
                "limit": 3,
                "rag_candidates": [{"product_id": self.product_ids[2], "relevance": 0.9}],
                "context": {"channel": "telegram", "query": "gift"},
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        payload = response.json()
        self.assertTrue(payload["request_id"])
        self.assertTrue(payload["items"])
        served_ids = {item["product_id"] for item in payload["items"]}
        self.assertIn(self.product_ids[2], served_ids)
        self.assertNotIn(self.product_ids[3], served_ids)

        product_id = payload["items"][0]["product_id"]
        feedback = {"product_id": product_id, "event_type": "purchase", "idempotency_key": "purchase-1"}
        first = self.client.post(f"/api/recommendations/{payload['request_id']}/feedback", headers=self.headers(), json=feedback)
        second = self.client.post(f"/api/recommendations/{payload['request_id']}/feedback", headers=self.headers(), json=feedback)
        self.assertEqual(201, first.status_code, first.text)
        self.assertEqual(201, second.status_code, second.text)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(1.0, first.json()["reward"])

    def test_rejects_customer_from_another_tenant(self):
        response = self.client.post(
            "/api/recommendations",
            headers=self.headers(self.other_business_id),
            json={"customer_id": self.customer_id},
        )
        self.assertEqual(404, response.status_code)

    def test_tracks_behavioral_events_and_auto_records_recommendation_impressions(self):
        click = {
            "customer_id": self.customer_id,
            "product_id": self.product_ids[2],
            "event_type": "click",
            "source": "web",
            "idempotency_key": "interaction-click-1",
        }
        first = self.client.post("/api/recommendations/interactions", headers=self.headers(), json=click)
        second = self.client.post("/api/recommendations/interactions", headers=self.headers(), json=click)
        self.assertEqual(201, first.status_code, first.text)
        self.assertEqual(first.json()["id"], second.json()["id"])

        asked = self.client.post(
            "/api/recommendations/interactions",
            headers=self.headers(),
            json={
                "customer_id": self.customer_id,
                "event_type": "ask",
                "source": "chatbot",
                "query": "product three gift",
                "idempotency_key": "interaction-ask-1",
            },
        )
        self.assertEqual(201, asked.status_code, asked.text)

        served = self.client.post(
            "/api/recommendations",
            headers=self.headers(),
            json={"customer_id": self.customer_id, "limit": 2},
        )
        self.assertEqual(201, served.status_code, served.text)
        summary = self.client.get(
            f"/api/recommendations/interactions/summary?customer_id={self.customer_id}",
            headers=self.headers(),
        )
        self.assertEqual(200, summary.status_code, summary.text)
        self.assertGreaterEqual(summary.json()["event_counts"].get("click", 0), 1)
        self.assertGreaterEqual(summary.json()["event_counts"].get("ask", 0), 1)
        self.assertGreaterEqual(summary.json()["event_counts"].get("impression", 0), 1)

        with Session(self.engine) as db:
            impressions = db.query(CustomerProductInteraction).filter(
                CustomerProductInteraction.business_id == self.business_id,
                CustomerProductInteraction.source == "recommendation",
                CustomerProductInteraction.event_type == "impression",
            ).count()
            self.assertGreaterEqual(impressions, 1)

    @patch("app.api.chat.call_llm", return_value="catalog answer")
    @patch("app.api.chat.reserve_ai_budget", return_value={"cost": 0})
    @patch("app.api.chat.retrieve", return_value=[])
    def test_rag_question_with_customer_is_recorded_as_recommendation_signal(self, *_mocks):
        response = self.client.post(
            "/api/chat",
            headers={**self.headers(), "X-Idempotency-Key": "rag-question-test-1"},
            json={"customer_id": self.customer_id, "query": "product three gift"},
        )
        self.assertEqual(200, response.status_code, response.text)
        with Session(self.engine) as db:
            event = db.query(CustomerProductInteraction).filter(
                CustomerProductInteraction.business_id == self.business_id,
                CustomerProductInteraction.idempotency_key == "rag-question:rag-question-test-1",
            ).one()
            self.assertEqual("ask", event.event_type)
            self.assertEqual("rag", event.source)
            self.assertEqual("product three gift", event.query_text)

    def test_completed_order_creates_idempotent_purchase_interactions(self):
        with Session(self.engine) as db:
            product = Product(
                business_id=self.other_business_id,
                sku="PURCHASE-INTERACTION",
                name="Purchase interaction product",
                price=Decimal("12"),
                stock_quantity=5,
            )
            completion_customer = Customer(
                business_id=self.other_business_id,
                channel="telegram",
                external_user_id="recommendation-completion-customer",
            )
            db.add_all([product, completion_customer])
            db.flush()
            order = Order(
                business_id=self.other_business_id,
                customer_id=completion_customer.id,
                order_number="REC-COMPLETED-INTERACTION",
                status="delivered",
                total_amount=product.price,
                paid_amount=product.price,
                payment_status="paid",
            )
            db.add(order)
            db.flush()
            item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=2,
                unit_price=product.price,
                line_total=product.price * 2,
                product_name_snapshot=product.name,
                sku_snapshot=product.sku,
            )
            db.add(item)
            transition_sales_order(
                db,
                order_id=order.id,
                to_status="completed",
                actor_id=None,
                business_id=self.other_business_id,
            )
            db.commit()
            purchase_events = db.query(CustomerProductInteraction).filter(
                CustomerProductInteraction.order_id == order.id,
                CustomerProductInteraction.event_type == "purchase",
            ).all()
            self.assertEqual(1, len(purchase_events))
            self.assertEqual(2, purchase_events[0].event_metadata["quantity"])

            record_order_purchase_interactions(db, order=order)
            db.commit()
            replayed_count = db.query(CustomerProductInteraction).filter(
                CustomerProductInteraction.order_id == order.id,
                CustomerProductInteraction.event_type == "purchase",
            ).count()
            self.assertEqual(1, replayed_count)

    def test_segment_training_runs_through_durable_job_queue(self):
        scheduled = self.client.post("/api/recommendations/training/segments", headers=self.headers())
        self.assertEqual(202, scheduled.status_code, scheduled.text)
        with Session(self.engine) as db:
            processed = dispatch_business_crm_jobs(db, self.business_id)
            self.assertGreaterEqual(processed, 1)
            run = db.query(RecommendationTrainingRun).filter_by(business_id=self.business_id).one()
            profiles = db.query(RecommendationCustomerProfile).filter_by(business_id=self.business_id).all()
            self.assertEqual("succeeded", run.status)
            self.assertEqual(2, len(profiles))
            self.assertTrue(all(profile.segment_label.startswith("cluster_") for profile in profiles))


if __name__ == "__main__":
    unittest.main()
