from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.bases import TenantBase
from app.models.business import Business
from app.models.business_setting import BusinessSetting
from app.models.customer import Customer
from app.models.customer_collection import CustomerConsent
from app.models.recommendation import CustomerProductInteraction, RecommendationCustomerProfile, RecommendationTrainingRun
from app.models.sales import Order, OrderItem, Product
from app.rag.evaluation import evaluate_product_rankings, evaluate_predictions
from app.schemas.recommendation import RecommendationRequestCreate
from app.services import recommendation_service as recommender
from app.services.recommendation_service import rag_personalization_weights
from app.services.rfm_segments import customer_rfm_profiles


@pytest.fixture
def shop(monkeypatch):
    engine = create_engine("sqlite://")
    Business.metadata.create_all(engine)
    TenantBase.metadata.create_all(engine)
    now = datetime(2026, 10, 20, 12)
    monkeypatch.setattr(recommender, "_now", lambda: now)
    from app.rag import llm_caller
    monkeypatch.setattr(llm_caller, "call_llm", lambda *_args, **_kwargs: pytest.fail("Personalization must not call an LLM"))
    with Session(engine) as db:
        business = Business(name="Shop", slug="rfm-shop")
        other = Business(name="Other", slug="rfm-other")
        db.add_all([business, other])
        db.flush()
        customer = Customer(business_id=business.id, channel="telegram", external_user_id="buyer")
        peer = Customer(business_id=business.id, channel="telegram", external_user_id="peer")
        stranger = Customer(business_id=other.id, channel="telegram", external_user_id="stranger")
        db.add_all([customer, peer, stranger])
        db.flush()
        db.add(CustomerConsent(business_id=business.id, customer_id=customer.id, purpose="personalization", status="granted"))
        db.add(BusinessSetting(business_id=business.id, key="customer_fact_extraction_enabled", value="true"))
        products = [
            Product(business_id=business.id, sku="SKU-RED", name="Bình đỏ", price=100, stock_quantity=10,
                    metadata_={"color": "red", "category": "binh"}),
            Product(business_id=business.id, sku="SKU-BLUE", name="Bình xanh", price=200, stock_quantity=10,
                    metadata_={"color": "blue", "category": "binh"}),
            Product(business_id=business.id, sku="SKU-EMPTY", name="Bình hết hàng", price=100, stock_quantity=0),
        ]
        db.add_all(products)
        db.commit()
        yield db, business, customer, peer, stranger, products, now
    engine.dispose()


def add_order(db, customer, now, *, status="completed", payment="paid", total=100, refund=0, days=40):
    number = str(db.query(Order).count() + 1)
    order = Order(business_id=customer.business_id, customer_id=customer.id, order_number=number,
                  status=status, payment_status=payment, total_amount=Decimal(total), refunded_amount=Decimal(refund),
                  created_at=now - timedelta(days=days), updated_at=now)
    db.add(order)
    db.flush()
    return order


def suggest(db, business, customer, **kwargs):
    return recommender.serve_recommendations(db, business_id=business.id,
        payload=RecommendationRequestCreate(customer_id=customer.id, limit=3, **kwargs))


def interest(db, business, customer, product, now, percent, suffix):
    db.add(CustomerProductInteraction(business_id=business.id, customer_id=customer.id, product_id=product.id,
        event_type="staff_interest", source="crm", idempotency_key=suffix,
        event_metadata={"interest_percent": percent}, occurred_at=now))
    db.commit()


def test_rfm_is_net_completed_sales_without_line_item_double_counting(shop):
    db, business, customer, peer, stranger, products, now = shop
    order = add_order(db, customer, now, total=100, refund=30)
    for product in products[:2]:
        db.add(OrderItem(order_id=order.id, product_id=product.id, quantity=2, unit_price=25, line_total=50,
                         product_name_snapshot=product.name, sku_snapshot=product.sku))
    add_order(db, customer, now, status="delivered", total=60)
    add_order(db, customer, now, status="cancelled", total=1000)
    add_order(db, customer, now, status="delivered", payment="unpaid", total=1000)
    add_order(db, customer, now, payment="refunded", total=100, refund=100)
    add_order(db, customer, now, total=1000, days=-1)
    add_order(db, peer, now, total=1000)
    add_order(db, stranger, now, total=99999)
    db.commit()
    profiles = customer_rfm_profiles(db, business.id, as_of=now)
    assert stranger.id not in profiles
    profile = profiles[customer.id]
    assert profile["frequency"] == 2
    assert profile["monetary"] == 130
    assert profile["total_items"] == 4
    assert profile["distinct_products"] == 2
    assert profile["avg_order_value"] == 65
    assert profile["rfm_scores"]["monetary"] == 1


def test_snapshot_reused_without_recomputing_preferences(shop, monkeypatch):
    db, business, customer, _, _, _, _ = shop
    first = suggest(db, business, customer)
    assert first.context["profile_cache_hit"] is False
    monkeypatch.setattr(recommender, "_customer_purchase_facets", lambda *_: pytest.fail("cache was not reused"))
    monkeypatch.setattr(recommender, "customer_rfm_profiles", lambda *_args, **_kwargs: pytest.fail("RFM was recomputed"))
    second = suggest(db, business, customer)
    assert second.context["profile_cache_hit"] is True
    assert [item["product_id"] for item in first.served_items] == [item["product_id"] for item in second.served_items]


def test_refund_and_status_changes_invalidate_same_second_snapshot(shop):
    db, business, customer, _, _, _, now = shop
    order = add_order(db, customer, now, total=100)
    db.commit()
    suggest(db, business, customer)
    order.refunded_amount = 30
    order.updated_at = now
    db.commit()
    assert suggest(db, business, customer).context["profile_cache_hit"] is False
    profile = db.query(RecommendationCustomerProfile).filter_by(customer_id=customer.id).one()
    assert profile.features["monetary"] == 70
    order.status = "cancelled"
    order.updated_at = now
    db.commit()
    assert suggest(db, business, customer).context["profile_cache_hit"] is False
    db.refresh(profile)
    assert profile.features["frequency"] == profile.features["monetary"] == 0
    assert profile.segment_label == "no_purchase"


def test_latest_manual_interest_replaces_old_value_and_rank(shop):
    db, business, customer, _, _, products, now = shop
    interest(db, business, customer, products[1], now - timedelta(minutes=2), 90, "old-interest")
    first = suggest(db, business, customer)
    assert first.served_items[0]["product_id"] == products[1].id
    interest(db, business, customer, products[1], now - timedelta(minutes=1), 0, "reset-interest")
    second = suggest(db, business, customer)
    assert second.context["profile_cache_hit"] is False
    assert second.served_items[0]["product_id"] == products[0].id


def test_preferences_cannot_override_budget_sku_stock_or_live_price(shop):
    db, business, customer, _, _, products, now = shop
    interest(db, business, customer, products[1], now - timedelta(minutes=1), 100, "blue-interest")
    assert [item["product_id"] for item in suggest(db, business, customer, query="dưới 150 đồng").served_items] == [products[0].id]
    assert [item["product_id"] for item in suggest(db, business, customer, query="SKU-RED").served_items] == [products[0].id]
    assert suggest(db, business, customer, query="SKU-EMPTY").served_items == []
    products[0].price = 120
    db.commit()
    assert suggest(db, business, customer, query="SKU-RED").served_items[0]["price"] == 120
    products[0].reserved_quantity = products[0].stock_quantity
    db.commit()
    assert suggest(db, business, customer, query="SKU-RED").served_items == []


def test_revoked_consent_immediately_stops_cached_personalization(shop):
    db, business, customer, _, _, products, now = shop
    interest(db, business, customer, products[1], now - timedelta(minutes=1), 100, "interest")
    suggest(db, business, customer)
    db.add(CustomerConsent(business_id=business.id, customer_id=customer.id, purpose="personalization", status="revoked"))
    db.commit()
    result = suggest(db, business, customer)
    assert result.customer_id is None
    assert result.context["profile_cache_hit"] is False
    assert result.context["personalization_applied"] is False


def test_rag_ppr_weights_use_saved_rfm_and_product_signals_only_with_consent(shop):
    db, business, customer, peer, _, products, _ = shop
    db.add(RecommendationCustomerProfile(
        business_id=business.id,
        customer_id=customer.id,
        segment_label="loyal",
        model_version="rfm_percentile_v1",
        features={
            "rfm_scores": {"recency": 5, "frequency": 4, "monetary": 5},
            "product_signal_cache": {"signals": {
                "recent": [products[1].id],
                "historical": [products[1].id],
                "interactions": {},
                "staff_interest": {},
            }},
        },
    ))
    db.commit()

    weights = rag_personalization_weights(
        db, business_id=business.id, customer_id=customer.id,
    )

    assert weights[f"id:{products[1].id}"] == 1.0
    assert weights["sku:sku-blue"] == 1.0
    assert rag_personalization_weights(
        db, business_id=business.id, customer_id=peer.id,
    ) is None


def test_training_precomputes_cache_using_same_tenant_population(shop):
    db, business, customer, peer, _, _, now = shop
    add_order(db, customer, now, total=100)
    add_order(db, peer, now, total=1000)
    run = RecommendationTrainingRun(business_id=business.id, algorithm="deterministic_rfm_kmeans", status="queued")
    db.add(run)
    db.commit()
    recommender.train_customer_segments(db, business_id=business.id, training_run_id=run.id)
    profile = db.query(RecommendationCustomerProfile).filter_by(customer_id=customer.id).one()
    assert profile.features["rfm_scores"]["monetary"] == 1
    assert profile.features["product_signal_cache"]["version"] == recommender.PERSONALIZATION_CACHE_VERSION
    assert suggest(db, business, customer).context["profile_cache_hit"] is True


def test_product_evaluation_penalizes_wrong_order_duplicates_and_forbidden_products():
    cases = [{"id": "rank", "expected_product_ids": [1, 2], "forbidden_product_ids": [99], "expected_rfm_segment": "loyal"}]
    predictions = [{"id": "rank", "recommended_product_ids": [99, 2, 2], "rfm_segment": "loyal"}]
    result = evaluate_product_rankings(cases, predictions, top_k=3)
    assert result["precision_at_k"] == pytest.approx(1 / 3, abs=1e-6)
    assert result["recall_at_k"] == result["mrr"] == 0.5
    assert 0 < result["ndcg_at_k"] < 0.5
    assert result["forbidden_product_rate"] == result["rfm_segment_accuracy"] == 1
    assert evaluate_product_rankings([{"id": "empty", "expected_product_ids": []}], [], top_k=3)["ndcg_at_k"] == 0
    assert evaluate_predictions(cases, predictions)["recommendation_metrics"]["case_count"] == 1
