import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.customer import Customer
from app.models.crm_extended import CustomerTag, Tag
from app.models.experimentation import BanditDecision, BanditPolicy, Experiment
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
    def test_rag_question_without_sources_uses_safe_fallback_and_records_minimal_signal(
        self, retrieve, reserve_budget, call_llm
    ):
        response = self.client.post(
            "/api/chat",
            headers={**self.headers(), "X-Idempotency-Key": "rag-question-test-1"},
            json={"customer_id": self.customer_id, "query": "product three gift"},
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("no_context", response.json()["answer_status"])
        self.assertTrue(response.json()["handoff_required"])
        self.assertEqual([], response.json()["sources"])
        self.assertIn("reliable source", response.json()["answer"].lower())
        retrieve.assert_called_once()
        reserve_budget.assert_not_called()
        call_llm.assert_not_called()
        with Session(self.engine) as db:
            event = db.query(CustomerProductInteraction).filter(
                CustomerProductInteraction.business_id == self.business_id,
                CustomerProductInteraction.idempotency_key == "rag-question:rag-question-test-1",
            ).one()
            self.assertEqual("ask", event.event_type)
            self.assertEqual("rag", event.source)
            self.assertIsNone(event.query_text)
            self.assertEqual(len("product three gift"), event.event_metadata["query_chars"])
            self.assertNotIn("query_hash", event.event_metadata)

    @patch("app.api.chat.stream_llm")
    @patch("app.api.chat.reserve_ai_budget")
    @patch("app.api.chat.retrieve", return_value=[])
    def test_stream_without_sources_emits_handoff_without_calling_llm(self, retrieve, reserve_budget, stream_llm):
        response = self.client.post(
            "/api/chat/stream",
            headers=self.headers(),
            json={"query": "Câu hỏi không có trong tài liệu"},
        )

        self.assertEqual(200, response.status_code, response.text)
        self.assertIn('"type": "sources"', response.text)
        self.assertIn('"answer_status": "no_context"', response.text)
        self.assertIn('"handoff_required": true', response.text)
        self.assertIn("nhân viên xác minh", response.text)
        retrieve.assert_called_once()
        reserve_budget.assert_not_called()
        stream_llm.assert_not_called()

    @patch("app.api.chat.stream_llm")
    @patch("app.api.chat.reserve_ai_budget", return_value={"cost": 0})
    @patch("app.api.chat.retrieve")
    def test_stream_provider_failure_replaces_partial_answer_with_safe_handoff(
        self, retrieve, _reserve_budget, stream_llm
    ):
        retrieve.return_value = [SimpleNamespace(
            chunk_id=12,
            document_id=7,
            content="Nội dung nguồn.",
            similarity=0.91,
            metadata={},
            filename="nguon.txt",
            chunk_index=0,
        )]

        async def partial_then_fail(_messages):
            yield "Câu trả lời chưa hoàn tất"
            raise RuntimeError("provider unavailable")

        stream_llm.side_effect = partial_then_fail
        response = self.client.post(
            "/api/chat/stream",
            headers=self.headers(),
            json={"query": "Hỏi nội dung tài liệu"},
        )

        self.assertEqual(200, response.status_code, response.text)
        self.assertIn('"code": "service_unavailable"', response.text)
        self.assertIn('"replace": true', response.text)
        self.assertIn("Trợ lý đang gặp sự cố", response.text)

    @patch("app.api.chat.call_llm", return_value="Giá là 10.000 đồng [Nguồn 1].")
    @patch("app.api.chat.reserve_ai_budget", return_value={"cost": 0})
    @patch("app.api.chat.retrieve")
    def test_chat_citations_include_document_and_chunk_identity(self, retrieve, *_mocks):
        retrieve.return_value = [SimpleNamespace(
            chunk_id=12,
            document_id=7,
            content="Giá sản phẩm là 10.000 đồng.",
            similarity=0.91,
            metadata={"topic": "pricing"},
            filename="bang-gia.txt",
            chunk_index=2,
        )]
        response = self.client.post(
            "/api/chat",
            headers=self.headers(),
            json={"query": "Giá sản phẩm là bao nhiêu?"},
        )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("answered", response.json()["answer_status"])
        self.assertFalse(response.json()["handoff_required"])
        self.assertEqual(
            {
                "document_id": 7,
                "content": "Giá sản phẩm là 10.000 đồng.",
                "similarity": 0.91,
                "metadata": {"topic": "pricing"},
                "citation_id": 1,
                "chunk_id": 12,
                "filename": "bang-gia.txt",
                "chunk_index": 2,
            },
            response.json()["sources"][0],
        )

    @patch("app.api.chat.call_llm", return_value="Giá là 10.000 đồng.")
    @patch("app.api.chat.reserve_ai_budget", return_value={"cost": 0})
    @patch("app.api.chat.retrieve")
    def test_chat_rejects_uncited_llm_answer(self, retrieve, *_mocks):
        retrieve.return_value = [SimpleNamespace(
            chunk_id=12, document_id=7, content="Giá sản phẩm là 10.000 đồng.",
            similarity=0.91, metadata={}, filename="bang-gia.txt", chunk_index=0,
        )]
        response = self.client.post(
            "/api/chat", headers=self.headers(), json={"query": "Giá sản phẩm?"},
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("no_context", response.json()["answer_status"])
        self.assertTrue(response.json()["handoff_required"])
        self.assertNotIn("Giá là 10.000 đồng.", response.text)

    @patch("app.api.chat.stream_llm")
    @patch("app.api.chat.reserve_ai_budget", return_value={"cost": 0})
    @patch("app.api.chat.retrieve")
    def test_stream_does_not_emit_uncited_partial_answer(self, retrieve, _reserve, stream_llm):
        retrieve.return_value = [SimpleNamespace(
            chunk_id=12, document_id=7, content="Giá sản phẩm là 10.000 đồng.",
            similarity=0.91, metadata={}, filename="bang-gia.txt", chunk_index=0,
        )]

        async def uncited(_messages):
            yield "Giá là "
            yield "10.000 đồng."

        stream_llm.side_effect = uncited
        response = self.client.post(
            "/api/chat/stream", headers=self.headers(), json={"query": "Giá sản phẩm?"},
        )
        self.assertEqual(200, response.status_code, response.text)
        self.assertIn('"answer_status": "no_context"', response.text)
        self.assertNotIn("Giá là 10.000 đồng.", response.text)

    @patch("app.api.chat.call_llm", side_effect=RuntimeError("provider unavailable; token=secret"))
    @patch("app.api.chat.reserve_ai_budget", return_value={"cost": 0})
    @patch("app.api.chat.retrieve")
    def test_provider_failure_returns_safe_handoff_fallback(self, retrieve, *_mocks):
        retrieve.return_value = [SimpleNamespace(
            chunk_id=12,
            document_id=7,
            content="Nội dung nguồn.",
            similarity=0.91,
            metadata={},
            filename="nguon.txt",
            chunk_index=0,
        )]
        response = self.client.post(
            "/api/chat",
            headers=self.headers(),
            json={"query": "Hỏi nội dung tài liệu"},
        )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("service_error", response.json()["answer_status"])
        self.assertTrue(response.json()["handoff_required"])
        self.assertIn("sự cố", response.json()["answer"].lower())
        self.assertNotIn("secret", response.text)

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
            self.assertTrue(all(profile.segment_label.startswith("rfm_cluster_") for profile in profiles))
            ai_tags = db.query(Tag).filter(
                Tag.business_id == self.business_id,
                Tag.name.like("RFM · AI nhóm %"),
            ).all()
            self.assertTrue(ai_tags)
            self.assertEqual(2, db.query(CustomerTag).filter(
                CustomerTag.business_id == self.business_id,
                CustomerTag.tag_id.in_([tag.id for tag in ai_tags]),
            ).count())

            experiment = Experiment(
                business_id=self.business_id,
                name="RFM strategy test",
                variants=["balanced", "personalized"],
                status="running",
            )
            db.add(experiment)
            db.flush()
            db.add(BanditPolicy(
                business_id=self.business_id,
                experiment_id=experiment.id,
                version="rfm-context-v1",
                epsilon=Decimal("0"),
                status="active",
                config={"objective": "terminal_conversion_reward"},
            ))
            db.commit()
            experiment_id = experiment.id

        response = self.client.post(
            "/api/recommendations",
            headers=self.headers(),
            json={"customer_id": self.customer_id, "experiment_id": experiment_id, "limit": 1},
        )
        self.assertEqual(201, response.status_code, response.text)
        with Session(self.engine) as db:
            decision = db.query(BanditDecision).filter_by(business_id=self.business_id, experiment_id=experiment_id).one()
            profile = db.query(RecommendationCustomerProfile).filter_by(
                business_id=self.business_id, customer_id=self.customer_id
            ).one()
            self.assertEqual(profile.segment_label, decision.context["rfm_segment"])


if __name__ == "__main__":
    unittest.main()
