from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import app.models  # noqa: F401 - register all tenant model tables
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.bases import TenantBase
from app.models.business import Business
from app.models.business_setting import BusinessSetting
from app.models.customer import Customer
from app.models.customer_collection import CustomerConsent
from app.models.recommendation import CustomerProductInteraction, RecommendationRequest
from app.models.sales import Product
from app.services.recommendation_interaction_service import record_recommendation_impressions
from app.services.recommendation_learning import (
    FEATURE_NAMES,
    LIVE_RERANKER_ALGORITHM,
    LIVE_RERANKER_BLEND_VERSION,
    blend_candidate_scores,
    candidate_features,
    live_reranker_blend_profile,
)
from scripts.train_live_recommendation_reranker import _load_groups, _ranking_metrics, _train


class RerankerBlendUnitTests(TestCase):
    def test_specific_and_discovery_queries_get_distinct_baseline_weights(self):
        self.assertEqual(("specific", 0.85), live_reranker_blend_profile("Áo cotton màu xanh size L"))
        self.assertEqual(("discovery", 0.65), live_reranker_blend_profile("Gợi ý sản phẩm cho mình"))

    def test_weighted_blend_retains_baseline_signal_and_uses_model_signal(self):
        baseline = {1: 0.90, 2: 0.70, 3: 0.20}
        model = {1: 0.10, 2: 0.90}

        blended = blend_candidate_scores(baseline, model, baseline_weight=0.85)

        self.assertGreater(blended[1], blended[2])
        self.assertEqual(0.0, blended[3])  # Missing model score falls back to normalized baseline.
        self.assertEqual(LIVE_RERANKER_BLEND_VERSION, "normalized_baseline_blend_v1")


class RerankerDatabaseTests(TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(self.engine)
        TenantBase.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            self.business = Business(name="Blend test", slug="blend-test")
            db.add(self.business)
            db.flush()
            self.business_id = self.business.id
            db.add(BusinessSetting(
                business_id=self.business_id,
                key="customer_fact_extraction_enabled",
                value="true",
            ))
            self.products = [
                Product(business_id=self.business_id, sku=f"BLEND-{index}", name=f"Item {index}",
                        price=Decimal("10"), stock_quantity=5)
                for index in (1, 2, 3)
            ]
            db.add_all(self.products)
            db.flush()
            self.product_ids = [product.id for product in self.products]
            db.commit()

    def tearDown(self):
        TenantBase.metadata.drop_all(self.engine)
        Business.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _customer(self, db: Session, suffix: str, *, opted_out: bool = False) -> Customer:
        customer = Customer(
            business_id=self.business_id,
            channel="telegram",
            external_user_id=f"blend-{suffix}",
            fact_extraction_opt_out=opted_out,
        )
        db.add(customer)
        db.flush()
        return customer

    def _request_with_impressions(self, db: Session, customer: Customer | None, name: str) -> RecommendationRequest:
        now = datetime.utcnow()
        candidates = [
            {"product_id": product_id, "rank": rank, "position": rank, "score": 1.0 / rank,
             "feature_snapshot": {"catalog_match_score": 1.0 / rank}}
            for rank, product_id in enumerate(self.product_ids[:2], start=1)
        ]
        request = RecommendationRequest(
            business_id=self.business_id,
            request_id=name,
            customer_id=customer.id if customer else None,
            strategy="rag",
            model_version="item_affinity_rfm_v5",
            context={"candidate_snapshot": candidates, "query": "áo cotton", "rfm_snapshot": {"frequency": 2}},
            served_items=candidates,
            created_at=now - timedelta(hours=1),
        )
        db.add(request)
        db.flush()
        for position, product_id in enumerate(self.product_ids[:2], start=1):
            db.add(CustomerProductInteraction(
                business_id=self.business_id,
                customer_id=customer.id if customer else None,
                product_id=product_id,
                recommendation_request_id=request.id,
                event_type="impression",
                source="test",
                idempotency_key=f"{name}-impression-{product_id}",
                event_metadata={"position": position},
                occurred_at=now,
            ))
        db.flush()
        return request

    def test_training_filters_consent_opt_out_and_shop_setting_before_features(self):
        with Session(self.engine) as db:
            eligible = self._customer(db, "granted")
            revoked = self._customer(db, "revoked")
            opted_out = self._customer(db, "opted-out", opted_out=True)
            no_consent = self._customer(db, "no-consent")
            db.add_all([
                CustomerConsent(business_id=self.business_id, customer_id=eligible.id,
                                purpose="personalization", status="granted"),
                CustomerConsent(business_id=self.business_id, customer_id=revoked.id,
                                purpose="personalization", status="granted"),
                CustomerConsent(business_id=self.business_id, customer_id=revoked.id,
                                purpose="personalization", status="revoked"),
                CustomerConsent(business_id=self.business_id, customer_id=opted_out.id,
                                purpose="personalization", status="granted"),
            ])
            db.flush()
            self._request_with_impressions(db, eligible, "eligible-request")
            legacy = self._request_with_impressions(db, eligible, "legacy-model-request")
            legacy.model_version = f"item_affinity_rfm_v5+{LIVE_RERANKER_ALGORITHM}"
            legacy.context = {
                **legacy.context,
                "behavioral_reranker": {"algorithm": LIVE_RERANKER_ALGORITHM},
            }
            self._request_with_impressions(db, revoked, "revoked-request")
            self._request_with_impressions(db, opted_out, "opted-out-request")
            self._request_with_impressions(db, no_consent, "missing-consent-request")
            with patch("scripts.train_live_recommendation_reranker.candidate_features", wraps=candidate_features) as feature_builder:
                groups = _load_groups(db, self.business_id, lookback_days=14)

            self.assertEqual(["eligible-request"], [group["request_id"] for group in groups])
            self.assertEqual(2, feature_builder.call_count)

            setting = db.query(BusinessSetting).filter_by(
                business_id=self.business_id,
                key="customer_fact_extraction_enabled",
            ).one()
            setting.value = "false"
            db.flush()
            self.assertEqual([], _load_groups(db, self.business_id, lookback_days=14))

    def test_impression_record_contains_blend_version_and_weights(self):
        with Session(self.engine) as db:
            customer = self._customer(db, "impression")
            db.add(CustomerConsent(
                business_id=self.business_id,
                customer_id=customer.id,
                purpose="personalization",
                status="granted",
            ))
            db.flush()
            item = {
                "product_id": self.product_ids[0],
                "position": 1,
                "score": 0.88,
                "feature_snapshot": {
                    "live_reranker_blend_version": LIVE_RERANKER_BLEND_VERSION,
                    "live_reranker_baseline_score": 0.73,
                    "live_reranker_blended_score": 0.88,
                },
            }
            request = RecommendationRequest(
                business_id=self.business_id,
                request_id="blend-impression-request",
                customer_id=customer.id,
                strategy="rag",
                model_version=LIVE_RERANKER_ALGORITHM,
                context={"behavioral_reranker": {
                    "algorithm": LIVE_RERANKER_ALGORITHM,
                    "blend_version": LIVE_RERANKER_BLEND_VERSION,
                    "applied": True,
                    "query_intent": "specific",
                    "retrieval_weight": 0.85,
                    "model_weight": 0.15,
                    "training_run_id": 17,
                    "candidate_pool_size": 3,
                    "scored_candidate_count": 3,
                }},
                served_items=[item],
                created_at=datetime.utcnow(),
            )
            db.add(request)
            db.flush()

            record_recommendation_impressions(db, request=request, source="test")
            event = db.query(CustomerProductInteraction).filter_by(
                recommendation_request_id=request.id,
                event_type="impression",
            ).one()

            self.assertEqual(LIVE_RERANKER_BLEND_VERSION, event.event_metadata["blend_version"])
            self.assertEqual(0.85, event.event_metadata["behavioral_reranker"]["retrieval_weight"])
            self.assertEqual(
                LIVE_RERANKER_BLEND_VERSION,
                event.event_metadata["feature_snapshot"]["live_reranker_blend_version"],
            )


class TemporalBlendEvaluationTests(TestCase):
    def test_holdout_metrics_compare_baseline_with_baseline_plus_reranker(self):
        candidates = [
            {"product_id": 1, "rank": 1, "position": 1, "score": 0.90,
             "feature_snapshot": {"catalog_match_score": 0.0}},
            {"product_id": 2, "rank": 2, "position": 2, "score": 0.89,
             "feature_snapshot": {"catalog_match_score": 1.0}},
            {"product_id": 3, "rank": 3, "position": 3, "score": 0.10,
             "feature_snapshot": {"catalog_match_score": 0.0}},
        ]
        members = [
            {**candidates[0], "relevance": 0, "logged_position": 1},
            {**candidates[1], "relevance": 3, "logged_position": 2},
            {**candidates[2], "relevance": 0, "logged_position": 3},
        ]
        group = {
            "members": members,
            "candidate_pool": candidates,
            "query": "áo cotton màu xanh size L",
            "propensity": 1.0,
            "rfm_snapshot": None,
            "personalization_allowed": False,
        }
        artifact = {
            "feature_names": list(FEATURE_NAMES),
            "means": {name: 0.0 for name in FEATURE_NAMES},
            "scales": {name: 1.0 for name in FEATURE_NAMES},
            "weights": {name: (2.0 if name == "catalog_match_score" else 0.0) for name in FEATURE_NAMES},
            "intercept": 0.0,
        }

        baseline = _ranking_metrics([group], ranking="baseline")
        blended = _ranking_metrics([group], artifact, ranking="blend")

        self.assertLess(baseline["ndcg_at_3"], blended["ndcg_at_3"])
        self.assertEqual(1, blended["positive_holdout_requests"])

    def test_train_uses_chronological_holdout_and_reports_blend_version(self):
        feature_width = len(FEATURE_NAMES)
        groups = []
        for day in range(6):
            candidates = [
                {"product_id": 1, "rank": 1, "position": 1, "score": 0.8,
                 "feature_snapshot": {"catalog_match_score": 0.1}},
                {"product_id": 2, "rank": 2, "position": 2, "score": 0.79,
                 "feature_snapshot": {"catalog_match_score": 0.9}},
                {"product_id": 3, "rank": 3, "position": 3, "score": 0.1,
                 "feature_snapshot": {"catalog_match_score": 0.0}},
            ]
            members = [
                {**candidates[0], "relevance": 0, "explicit_negative": True,
                 "features": np.zeros(feature_width).tolist()},
                {**candidates[1], "relevance": 1, "explicit_negative": False,
                 "features": np.ones(feature_width).tolist()},
                {**candidates[2], "relevance": 0, "explicit_negative": True,
                 "features": np.zeros(feature_width).tolist()},
            ]
            groups.append({
                "request_id": f"temporal-{day}",
                "customer_id": 17,
                "created_at": datetime(2026, 1, 1) + timedelta(days=day),
                "query": "áo cotton",
                "candidate_pool": candidates,
                "members": members,
                "propensity": 1.0,
                "rfm_snapshot": None,
                "personalization_allowed": False,
                "positive_count": 1,
                "event_counts": {"impression": 3, "click": 1, "cart": 0, "purchase": 0, "skip": 0},
            })
        args = SimpleNamespace(
            min_positive_events=1,
            min_training_pairs=1,
            min_training_requests=1,
            min_holdout_requests=1,
            min_consented_customers=1,
        )

        artifact, metrics = _train(groups, args)

        self.assertIsNotNone(artifact)
        self.assertEqual("chronological_80_20", metrics["split_method"])
        self.assertLess(metrics["training_end"], metrics["holdout_start"])
        self.assertIn("baseline_ndcg_at_3", metrics)
        self.assertIn("blended_ndcg_at_3", metrics)
        self.assertEqual(0.63093, metrics["baseline_ndcg_at_3"])
        self.assertEqual(1.0, metrics["blended_ndcg_at_3"])
        self.assertGreater(metrics["blended_ndcg_at_3"], metrics["baseline_ndcg_at_3"])
        self.assertEqual(LIVE_RERANKER_BLEND_VERSION, metrics["blend_version"])
