import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.dependencies import get_db
from app.main import app
from app.models.business import Business
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.customer_fact import CustomerFact
from app.models.crm_job import CrmJob
from app.models.crm_extended import CustomerTag, Tag
from app.models.experimentation import BanditArmStat, BanditDecision, BanditPolicy, Experiment
from app.models.recommendation import (
    CustomerProductInteraction,
    RecommendationCustomerProfile,
    RecommendationFeedback,
    RecommendationRequest,
    RecommendationTrainingRun,
)
from app.models.message import Message
from app.models.sales import Order, OrderItem, Product
from app.services.crm_job_worker import _dispatch_weekly_customer_learning, dispatch_business_crm_jobs
from app.services.order_service import transition_sales_order
from app.services.recommendation_interaction_service import record_order_purchase_interactions
from app.services.recommendation_service import _personalization_allowed, _preferred_color, _product_matches_color
from app.services.recommendation_interaction_service import (
    record_explicit_chat_recommendation_decline,
    record_order_refund_interactions,
)


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

    def test_previously_purchased_pink_items_boost_matching_catalog_color(self):
        with Session(self.engine) as db:
            pink_bought = Product(
                business_id=self.business_id,
                sku="PINK-BOUGHT",
                name="Túi đeo hồng",
                price=Decimal("100"),
                stock_quantity=0,
                metadata_={"color": "hồng", "category": "phụ kiện"},
            )
            pink_candidate = Product(
                business_id=self.business_id,
                sku="PINK-CANDIDATE",
                name="Bình nước pastel",
                price=Decimal("15"),
                stock_quantity=5,
                metadata_={"color": "pink"},
            )
            blue_candidate = Product(
                business_id=self.business_id,
                sku="BLUE-CANDIDATE",
                name="Bình nước xanh",
                price=Decimal("15"),
                stock_quantity=5,
                metadata_={"color": "blue"},
            )
            db.add_all([pink_bought, pink_candidate, blue_candidate])
            db.flush()
            pink_candidate_id = int(pink_candidate.id)
            order = Order(
                business_id=self.business_id,
                customer_id=self.customer_id,
                order_number="PINK-AFFINITY",
                status="completed",
                total_amount=Decimal("100"),
            )
            db.add(order)
            db.flush()
            db.add(OrderItem(
                order_id=order.id,
                product_id=pink_bought.id,
                quantity=2,
                unit_price=Decimal("50"),
                line_total=Decimal("100"),
            ))
            db.commit()

            color, signal = _preferred_color(db, self.business_id, self.customer_id)
            self.assertEqual("pink", color)
            self.assertEqual("purchased_color_affinity", signal)
            self.assertTrue(_product_matches_color(pink_candidate, color))
            self.assertFalse(_product_matches_color(blue_candidate, color))

    def test_customer_fact_opt_out_disables_personalized_ranking(self):
        with Session(self.engine) as db:
            customer = db.get(Customer, self.customer_id)
            db.add(CustomerFact(
                business_id=self.business_id,
                customer_id=self.customer_id,
                fact_type="preference",
                fact_key="preferred_color",
                fact_value_json="pink",
                confidence=0.99,
                source_type="manual",
                is_verified=True,
            ))
            db.flush()
            self.assertTrue(_personalization_allowed(db, self.business_id, self.customer_id))
            customer.fact_extraction_opt_out = True
            db.commit()
            self.assertFalse(_personalization_allowed(db, self.business_id, self.customer_id))
            self.assertEqual((None, None), _preferred_color(db, self.business_id, self.customer_id))

        ranked = self.client.post(
            "/api/recommendations",
            headers=self.headers(),
            json={"customer_id": self.customer_id, "limit": 10},
        )
        self.assertEqual(201, ranked.status_code, ranked.text)
        self.assertIsNone(ranked.json()["customer_id"])
        self.assertFalse(any(
            item["reason"] in {"explicit_color_preference", "purchased_color_affinity"}
            for item in ranked.json()["items"]
        ))
        with Session(self.engine) as db:
            db.get(Customer, self.customer_id).fact_extraction_opt_out = False
            db.query(CustomerFact).filter(
                CustomerFact.business_id == self.business_id,
                CustomerFact.customer_id == self.customer_id,
                CustomerFact.fact_key == "preferred_color",
                CustomerFact.source_type == "manual",
            ).delete(synchronize_session=False)
            db.commit()

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

    def test_bot_recommendation_purchase_and_refund_train_bandit_once(self):
        with Session(self.engine) as db:
            conversation = Conversation(
                business_id=self.business_id,
                customer_id=self.customer_id,
                channel="telegram",
            )
            experiment = Experiment(
                business_id=self.business_id,
                name="Chat recommendation learning",
                variants=["balanced", "personalized"],
                status="running",
            )
            db.add_all([conversation, experiment])
            db.flush()
            db.add(BanditPolicy(
                business_id=self.business_id,
                experiment_id=experiment.id,
                version="recommendation-runtime-v1",
                epsilon=Decimal("0"),
                status="active",
                config={"objective": "terminal_conversion_reward"},
            ))
            db.commit()
            conversation_id = conversation.id
            experiment_id = experiment.id

        served = self.client.post(
            "/api/recommendations",
            headers=self.headers(),
            json={"customer_id": self.customer_id, "experiment_id": experiment_id, "limit": 3},
        )
        self.assertEqual(201, served.status_code, served.text)
        request_id = served.json()["request_id"]
        item_id = served.json()["items"][0]["product_id"]
        with Session(self.engine) as db:
            request = db.query(RecommendationRequest).filter_by(
                business_id=self.business_id, request_id=request_id,
            ).one()
            decision_id = request.bandit_decision_id
            db.add(Message(
                conversation_id=conversation_id,
                channel="telegram",
                sender_type="bot",
                direction="outbound",
                status="sent",
                content="Gợi ý sản phẩm",
                sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
                metadata_={"recommendation": {
                    "request_id": request_id,
                    "product_ids": [item["product_id"] for item in request.served_items],
                    "source_channel": "telegram",
                }},
            ))
            order = Order(
                business_id=self.business_id,
                customer_id=self.customer_id,
                conversation_id=conversation_id,
                order_number="REC-ATTRIBUTED-1",
                status="completed",
                total_amount=Decimal("30"),
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.add(order)
            db.flush()
            db.add(OrderItem(
                order_id=order.id,
                product_id=item_id,
                quantity=1,
                unit_price=Decimal("30"),
                line_total=Decimal("30"),
            ))
            db.flush()
            record_order_purchase_interactions(db, order=order)
            db.commit()

            purchase = db.query(CustomerProductInteraction).filter_by(
                business_id=self.business_id,
                order_id=order.id,
                event_type="purchase",
            ).one()
            self.assertEqual(request.id, purchase.recommendation_request_id)
            decision = db.get(BanditDecision, decision_id)
            self.assertEqual(Decimal("1.0000"), decision.reward)
            stat = db.query(BanditArmStat).filter_by(
                business_id=self.business_id,
                policy_id=decision.policy_id,
                arm=decision.arm,
                context_hash=decision.context_hash,
            ).one()
            self.assertEqual(1, stat.pulls)
            self.assertEqual(Decimal("1.000000"), stat.reward_sum)

            order.status = "refunded"
            record_order_refund_interactions(db, order=order)
            db.commit()
            self.assertEqual(Decimal("-1.0000"), decision.reward)
            self.assertEqual(1, stat.pulls)
            self.assertEqual(Decimal("-1.000000"), stat.reward_sum)
            self.assertEqual(1, db.query(RecommendationFeedback).filter_by(
                business_id=self.business_id,
                recommendation_request_id=request.id,
                product_id=item_id,
                event_type="purchase",
            ).count())
            self.assertEqual(1, db.query(RecommendationFeedback).filter_by(
                business_id=self.business_id,
                recommendation_request_id=request.id,
                product_id=item_id,
                event_type="refund",
            ).count())

    def test_signed_product_link_records_click_before_redirect(self):
        with Session(self.engine) as db:
            product = db.get(Product, self.product_ids[2])
            product.product_url = "https://shop.example/products/product-three"
            db.commit()

        with patch("app.services.recommendation_service.settings.PUBLIC_BASE_URL", "http://testserver"):
            served = self.client.post(
                "/api/recommendations",
                headers=self.headers(),
                json={"customer_id": self.customer_id, "limit": 3},
            )
        self.assertEqual(201, served.status_code, served.text)
        item = next(item for item in served.json()["items"] if item["product_id"] == self.product_ids[2])
        self.assertTrue(item["click_url"])
        link = urlsplit(item["click_url"])
        clicked = self.client.get(link.path + "?" + link.query, follow_redirects=False)
        self.assertEqual(307, clicked.status_code)
        self.assertEqual("https://shop.example/products/product-three", clicked.headers["location"])
        with Session(self.engine) as db:
            self.assertEqual(1, db.query(RecommendationFeedback).filter_by(
                business_id=self.business_id,
                recommendation_request_id=db.query(RecommendationRequest.id).filter_by(
                    business_id=self.business_id,
                    request_id=served.json()["request_id"],
                ).scalar(),
                product_id=self.product_ids[2],
                event_type="click",
            ).count())

    def test_explicit_customer_decline_is_a_deduplicated_negative_signal(self):
        with Session(self.engine) as db:
            conversation = Conversation(
                business_id=self.business_id,
                customer_id=self.customer_id,
                channel="telegram",
            )
            db.add(conversation)
            db.commit()
            conversation_id = conversation.id
        served = self.client.post(
            "/api/recommendations",
            headers=self.headers(),
            json={"customer_id": self.customer_id, "limit": 3},
        )
        self.assertEqual(201, served.status_code, served.text)
        request_id = served.json()["request_id"]
        product_id = served.json()["items"][0]["product_id"]
        with Session(self.engine) as db:
            request = db.query(RecommendationRequest).filter_by(
                business_id=self.business_id, request_id=request_id,
            ).one()
            db.add_all([
                Message(
                    conversation_id=conversation_id,
                    channel="telegram",
                    sender_type="bot",
                    direction="outbound",
                    status="sent",
                    content="Mình gợi ý mẫu này",
                    metadata_={"recommendation": {"request_id": request_id}},
                ),
                Message(
                    conversation_id=conversation_id,
                    channel="telegram",
                    sender_type="customer",
                    direction="inbound",
                    status="received",
                    content="Mẫu này mình không thích, không hợp.",
                ),
            ])
            db.commit()
            self.assertTrue(record_explicit_chat_recommendation_decline(
                db,
                business_id=self.business_id,
                conversation_id=conversation_id,
                text="Mẫu này mình không thích, không hợp.",
            ))
            db.commit()
            self.assertEqual(1, db.query(RecommendationFeedback).filter_by(
                business_id=self.business_id,
                recommendation_request_id=request.id,
                product_id=product_id,
                event_type="skip",
            ).count())
            signal = db.query(CustomerProductInteraction).filter_by(
                business_id=self.business_id,
                recommendation_request_id=request.id,
                product_id=product_id,
                event_type="skip",
            ).one()
            self.assertEqual("explicit_decline", signal.event_metadata["signal"])

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

    @patch("app.api.chat.call_llm")
    @patch("app.api.chat.reserve_ai_budget")
    @patch("app.api.chat.retrieve")
    def test_rag_safety_issue_gets_immediate_safe_handoff_without_model_or_retrieval(
        self, retrieve, reserve_budget, call_llm
    ):
        response = self.client.post(
            "/api/chat",
            headers=self.headers(),
            json={"query": "Thiết bị có mùi khét thì tôi nên làm gì?"},
        )

        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        self.assertEqual("handoff_required", payload["answer_status"])
        self.assertTrue(payload["handoff_required"])
        self.assertIn("ngừng sử dụng", payload["answer"])
        self.assertEqual([], payload["sources"])
        retrieve.assert_not_called()
        reserve_budget.assert_not_called()
        call_llm.assert_not_called()

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
    @patch("app.api.chat.reserve_ai_budget")
    @patch("app.api.chat.retrieve")
    def test_stream_direct_staff_request_is_handed_off_without_retrieval(
        self, retrieve, reserve_budget, stream_llm
    ):
        response = self.client.post(
            "/api/chat/stream",
            headers=self.headers(),
            json={"query": "Cho tôi nói chuyện với nhân viên"},
        )

        self.assertEqual(200, response.status_code, response.text)
        self.assertIn('"answer_status": "handoff_required"', response.text)
        self.assertIn('"handoff_required": true', response.text)
        self.assertIn("nhân viên", response.text)
        retrieve.assert_not_called()
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
            self.assertEqual("telegram", decision.context["source_channel"])
            self.assertEqual("warmup_default", decision.selection_reason)
            db.add(BanditArmStat(
                business_id=self.business_id,
                policy_id=decision.policy_id,
                arm="balanced",
                context_hash=decision.context_hash,
                pulls=20,
                reward_sum=Decimal("15"),
            ))
            db.commit()

        learned_response = self.client.post(
            "/api/recommendations",
            headers=self.headers(),
            json={"customer_id": self.customer_id, "experiment_id": experiment_id, "limit": 1},
        )
        self.assertEqual(201, learned_response.status_code, learned_response.text)
        with Session(self.engine) as db:
            learned = db.query(BanditDecision).filter_by(
                business_id=self.business_id, experiment_id=experiment_id
            ).order_by(BanditDecision.id.desc()).first()
            self.assertEqual("exploitation", learned.selection_reason)
            self.assertEqual("balanced", learned.arm)

    def test_completed_weekly_fact_scan_queues_rfm_profile_refresh_once(self):
        business_id = self.other_business_id
        with Session(self.engine) as db:
            with patch(
                "app.services.crm_job_worker.dispatch_weekly_customer_fact_scan",
                return_value={"scanned": 2, "extracted_facts": 1, "has_more": False},
                ):
                result = _dispatch_weekly_customer_learning(db, business_id)
            db.commit()
            self.assertFalse(result["has_more"])
            weekly_jobs = db.query(CrmJob).filter(
                CrmJob.business_id == business_id,
                CrmJob.kind == "recommendations.train_segments",
                CrmJob.idempotency_key.like("recommendations:weekly-segments:%"),
            ).all()
            self.assertEqual(1, len(weekly_jobs))
            run = db.query(RecommendationTrainingRun).filter(
                RecommendationTrainingRun.id == weekly_jobs[0].payload["training_run_id"],
            ).one()
            self.assertEqual("queued", run.status)
            self.assertEqual("weekly_customer_learning", run.artifact["trigger"])


if __name__ == "__main__":
    unittest.main()
