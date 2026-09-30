"""Recommendation pipeline: source -> filter -> scorer -> selector -> feedback."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.experimentation import BanditArmStat, BanditDecision, BanditPolicy, Experiment
from app.models.recommendation import (
    RecommendationCustomerProfile,
    RecommendationFeedback,
    RecommendationRequest,
    RecommendationTrainingRun,
    CustomerProductInteraction,
)
from app.models.sales import Order, OrderItem, Product
from app.schemas.recommendation import RecommendationRequestCreate
from app.services.recommendation_artifacts import RecommendationArtifactError, registry as artifact_registry
from app.services.recommendation_interaction_service import (
    record_interaction,
    record_recommendation_impressions,
)


REVENUE_ORDER_STATUSES = ("confirmed", "processing", "shipped", "delivered", "completed", "paid")
MODEL_VERSION = "item_affinity_v1"
SEGMENT_MODEL_VERSION = "rfm_kmeans_v1"
STRATEGIES = {"balanced", "personalized", "popular", "rag"}
REWARDS = {
    "impression": Decimal("0"),
    "click": Decimal("0.2"),
    "cart": Decimal("0.5"),
    "purchase": Decimal("1"),
    "skip": Decimal("0"),
    "refund": Decimal("-1"),
}
TERMINAL_REWARD_EVENTS = {"purchase", "skip", "refund"}
INTERACTION_WEIGHTS = {
    "view": 0.05,
    "impression": 0.0,
    "click": 0.25,
    "cart": 0.60,
    "purchase": 1.0,
    "skip": -0.35,
    "refund": -1.0,
}
INTERACTION_HALF_LIFE_DAYS = 45


class RecommendationServiceError(ValueError):
    def __init__(self, detail: str, status_code: int = 422):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _context_hash(context: dict) -> str:
    encoded = json.dumps(context or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _customer_or_raise(db: Session, business_id: int, customer_id: int | None) -> Customer | None:
    if customer_id is None:
        return None
    customer = db.query(Customer).filter(
        Customer.id == customer_id,
        Customer.business_id == business_id,
        Customer.status != "merged",
    ).first()
    if customer is None:
        raise RecommendationServiceError("Khách hàng không tồn tại trong shop này.", 404)
    return customer


def _select_strategy(
    db: Session,
    *,
    business_id: int,
    payload: RecommendationRequestCreate,
    subject_key: str,
) -> tuple[str, int | None]:
    if payload.experiment_id is None:
        return "balanced", None
    experiment = db.query(Experiment).filter(
        Experiment.id == payload.experiment_id,
        Experiment.business_id == business_id,
    ).first()
    if experiment is None:
        raise RecommendationServiceError("Experiment không tồn tại trong shop này.", 404)
    if experiment.status != "running":
        raise RecommendationServiceError("Experiment recommendation phải ở trạng thái running.", 409)
    variants = [str(item).strip() for item in (experiment.variants or [])]
    if not variants or any(item not in STRATEGIES for item in variants):
        raise RecommendationServiceError("Variants chỉ được dùng: balanced, personalized, popular, rag.")
    policy = db.query(BanditPolicy).filter(
        BanditPolicy.business_id == business_id,
        BanditPolicy.experiment_id == experiment.id,
        BanditPolicy.status == "active",
    ).order_by(BanditPolicy.id.desc()).first()
    if policy is None:
        policy = BanditPolicy(
            business_id=business_id,
            experiment_id=experiment.id,
            version="recommendation-v1",
            epsilon=Decimal("0.10"),
            config={"objective": "terminal_conversion_reward"},
            status="active",
        )
        db.add(policy)
        db.flush()
    context_hash = _context_hash(payload.context)
    seed = int(hashlib.sha256(f"{subject_key}:{context_hash}:{policy.version}".encode()).hexdigest(), 16)
    stats = {
        arm: db.query(BanditArmStat).filter(
            BanditArmStat.policy_id == policy.id,
            BanditArmStat.arm == arm,
            BanditArmStat.context_hash == context_hash,
        ).first()
        for arm in variants
    }
    explore = (seed % 1_000_000) / 1_000_000 < float(policy.epsilon)
    if explore or not any(stat and stat.pulls for stat in stats.values()):
        strategy, reason = variants[seed % len(variants)], "exploration"
    else:
        strategy = max(variants, key=lambda arm: (float((stats[arm].reward_sum or 0) / max(1, stats[arm].pulls)), arm))
        reason = "exploitation"
    decision = BanditDecision(
        business_id=business_id,
        experiment_id=experiment.id,
        subject_key=subject_key,
        arm=strategy,
        context=payload.context,
        policy_id=policy.id,
        policy_version=policy.version,
        context_hash=context_hash,
        selection_reason=reason,
    )
    db.add(decision)
    db.flush()
    return strategy, decision.id


def _recent_and_historical_products(db: Session, business_id: int, customer_id: int | None) -> tuple[set[int], set[int]]:
    if customer_id is None:
        return set(), set()
    base = db.query(OrderItem.product_id, Order.created_at).join(Order, Order.id == OrderItem.order_id).filter(
        Order.business_id == business_id,
        Order.customer_id == customer_id,
        Order.status.in_(REVENUE_ORDER_STATUSES),
    )
    rows = base.all()
    historical = {int(product_id) for product_id, _ in rows}
    cutoff = _now() - timedelta(days=30)
    recent = {int(product_id) for product_id, created_at in rows if created_at and created_at >= cutoff}
    return recent, historical


def _customer_recommendation_features(db: Session, business_id: int, customer_id: int | None) -> dict[str, float]:
    """Build the exact RFM-like fields expected by the Colab demo artifacts."""
    if customer_id is None:
        return {
            "recency_days": 365.0,
            "frequency": 0.0,
            "monetary": 0.0,
            "total_items": 0.0,
            "distinct_products": 0.0,
            "avg_order_value": 0.0,
        }
    orders = db.query(Order).filter(
        Order.business_id == business_id,
        Order.customer_id == customer_id,
        Order.status.in_(REVENUE_ORDER_STATUSES),
    ).all()
    order_ids = [order.id for order in orders]
    item_rows = []
    if order_ids:
        item_rows = db.query(OrderItem.product_id, OrderItem.quantity).filter(OrderItem.order_id.in_(order_ids)).all()
    latest = max((order.created_at for order in orders if order.created_at), default=None)
    monetary = float(sum((Decimal(order.total_amount or 0) for order in orders), Decimal("0")))
    frequency = len(orders)
    return {
        "recency_days": float((_now() - latest).days if latest else 365),
        "frequency": float(frequency),
        "monetary": monetary,
        "total_items": float(sum(int(quantity or 0) for _, quantity in item_rows)),
        "distinct_products": float(len({int(product_id) for product_id, _ in item_rows})),
        "avg_order_value": monetary / max(1, frequency),
    }


def _demo_artifact_scores(customer: Customer | None, candidates: list[Product], features: dict[str, float]) -> tuple[int | None, dict[str, float], dict[str, float]]:
    """Use imported checkpoints only when exact public ID/SKU mappings exist."""
    try:
        segment = artifact_registry.demo_segmentation_label(features)
        skus = [str(product.sku) for product in candidates]
        linucb = artifact_registry.demo_linucb_scores(skus, features, segment)
        ncf = artifact_registry.demo_ncf_scores(customer.id if customer else None, skus)
        return segment, linucb, ncf
    except RecommendationArtifactError:
        # A missing/corrupt optional demo artifact must never make CRM serving
        # unavailable. Artifact status exposes the operational reason.
        return None, {}, {}


def _co_purchase_counts(db: Session, business_id: int, historical_products: set[int]) -> Counter:
    if not historical_products:
        return Counter()
    related_order_ids = select(OrderItem.order_id).join(Order, Order.id == OrderItem.order_id).where(
        Order.business_id == business_id,
        Order.status.in_(REVENUE_ORDER_STATUSES),
        OrderItem.product_id.in_(historical_products),
    )
    rows = db.query(OrderItem.product_id, func.count(OrderItem.id)).filter(
        OrderItem.order_id.in_(related_order_ids),
    ).group_by(OrderItem.product_id).all()
    return Counter({int(product_id): int(count) for product_id, count in rows})


def _popular_counts(db: Session, business_id: int) -> Counter:
    rows = db.query(OrderItem.product_id, func.count(OrderItem.id)).join(Order, Order.id == OrderItem.order_id).filter(
        Order.business_id == business_id,
        Order.status.in_(REVENUE_ORDER_STATUSES),
    ).group_by(OrderItem.product_id).all()
    return Counter({int(product_id): int(count) for product_id, count in rows})


def _interaction_scores(
    db: Session,
    *,
    business_id: int,
    customer_id: int | None = None,
) -> Counter:
    """Weighted, time-decayed product signals from view through refund."""
    query = db.query(
        CustomerProductInteraction.product_id,
        CustomerProductInteraction.event_type,
        CustomerProductInteraction.occurred_at,
        CustomerProductInteraction.event_metadata,
    ).filter(
        CustomerProductInteraction.business_id == business_id,
        CustomerProductInteraction.product_id.is_not(None),
        CustomerProductInteraction.event_type.in_(tuple(INTERACTION_WEIGHTS)),
    )
    if customer_id is not None:
        query = query.filter(CustomerProductInteraction.customer_id == customer_id)
    signals: Counter = Counter()
    now = _now()
    for product_id, event_type, occurred_at, metadata in query.all():
        days_old = max(0, (now - occurred_at).days) if occurred_at else INTERACTION_HALF_LIFE_DAYS
        decay = 0.5 ** (days_old / INTERACTION_HALF_LIFE_DAYS)
        quantity = (metadata or {}).get("quantity", 1)
        try:
            multiplier = min(5, max(1, int(quantity)))
        except (TypeError, ValueError):
            multiplier = 1
        signals[int(product_id)] += INTERACTION_WEIGHTS[str(event_type)] * decay * multiplier
    return signals


def _historic_query_tokens(db: Session, business_id: int, customer_id: int | None) -> Counter:
    if customer_id is None:
        return Counter()
    rows = db.query(CustomerProductInteraction.query_text).filter(
        CustomerProductInteraction.business_id == business_id,
        CustomerProductInteraction.customer_id == customer_id,
        CustomerProductInteraction.event_type.in_(("ask", "search")),
        CustomerProductInteraction.query_text.is_not(None),
    ).order_by(CustomerProductInteraction.occurred_at.desc()).limit(100).all()
    return Counter(token for (query,) in rows for token in _tokens(query or ""))


def _tokens(value: str) -> list[str]:
    return [token for token in re.findall(r"\w+", value.lower()) if len(token) > 1]


def _query_overlap(query: str | None, product: Product) -> float:
    tokens = set(_tokens(query or ""))
    if not tokens:
        return 0.0
    searchable = set(_tokens(f"{product.name} {product.description or ''}"))
    return sum(token in searchable for token in tokens) / len(tokens)


def _historic_interest_overlap(tokens: Counter, product: Product) -> float:
    if not tokens:
        return 0.0
    product_tokens = set(_tokens(f"{product.name} {product.description or ''}"))
    matched = sum(tokens[token] for token in product_tokens)
    return min(1.0, matched / max(1, max(tokens.values()) * 2))


def _score(strategy: str, affinity: float, popularity: float, rag: float, lexical: float) -> float:
    weights = {
        "balanced": (0.45, 0.20, 0.30, 0.05),
        "personalized": (0.70, 0.15, 0.10, 0.05),
        "popular": (0.10, 0.75, 0.10, 0.05),
        "rag": (0.20, 0.10, 0.65, 0.05),
    }[strategy]
    return sum(value * weight for value, weight in zip((affinity, popularity, rag, lexical), weights))


def serve_recommendations(db: Session, *, business_id: int, payload: RecommendationRequestCreate) -> RecommendationRequest:
    customer = _customer_or_raise(db, business_id, payload.customer_id)
    subject_key = f"customer:{customer.id}" if customer else "anonymous"
    strategy, bandit_decision_id = _select_strategy(db, business_id=business_id, payload=payload, subject_key=subject_key)
    recent, historical = _recent_and_historical_products(db, business_id, customer.id if customer else None)
    candidates = db.query(Product).filter(
        Product.business_id == business_id,
        Product.status == "active",
        Product.stock_quantity > Product.reserved_quantity,
    ).order_by(Product.id.asc()).all()
    candidates = [product for product in candidates if product.id not in recent]
    customer_features = _customer_recommendation_features(db, business_id, customer.id if customer else None)
    artifact_segment, linucb_scores, ncf_scores = _demo_artifact_scores(customer, candidates, customer_features)
    popularity = _popular_counts(db, business_id)
    affinity = _co_purchase_counts(db, business_id, historical)
    interaction_affinity = _interaction_scores(db, business_id=business_id, customer_id=customer.id if customer else None)
    interaction_popularity = _interaction_scores(db, business_id=business_id)
    historic_tokens = _historic_query_tokens(db, business_id, customer.id if customer else None)
    rag_scores = {candidate.product_id: candidate.relevance for candidate in payload.rag_candidates}
    popularity_signal = Counter(popularity)
    popularity_signal.update(interaction_popularity)
    max_popularity = max(popularity_signal.values(), default=1)
    max_affinity = max(
        max(affinity.values(), default=0),
        max((abs(value) for value in interaction_affinity.values()), default=0),
        1,
    )
    scored_items = []
    for product in candidates:
        co_purchase_score = float(affinity.get(product.id, 0) / max_affinity)
        interaction_score = float(interaction_affinity.get(product.id, 0) / max_affinity)
        affinity_score = max(-1.0, min(1.0, 0.65 * co_purchase_score + 0.35 * interaction_score))
        popularity_score = float(popularity_signal.get(product.id, 0) / max_popularity)
        rag_score = float(rag_scores.get(product.id, 0.0))
        current_query_score = _query_overlap(payload.query, product)
        historic_query_score = _historic_interest_overlap(historic_tokens, product)
        lexical_score = max(current_query_score, 0.35 * historic_query_score)
        score = _score(strategy, affinity_score, popularity_score, rag_score, lexical_score)
        sku = str(product.sku)
        ncf_score = ncf_scores.get(sku)
        linucb_score = linucb_scores.get(sku)
        if ncf_score is not None and linucb_score is not None:
            score = 0.55 * score + 0.25 * ncf_score + 0.20 * linucb_score
            reason = "ncf_and_linucb_demo_rerank"
        elif ncf_score is not None:
            score = 0.70 * score + 0.30 * ncf_score
            reason = "ncf_demo_rerank"
        elif linucb_score is not None:
            score = 0.70 * score + 0.30 * linucb_score
            reason = "linucb_demo_rerank"
        elif rag_score > 0:
            reason = "rag_relevance"
        elif interaction_score > 0:
            reason = "customer_interaction_affinity"
        elif affinity_score > 0:
            reason = "co_purchase_affinity"
        elif historic_query_score > 0:
            reason = "repeated_question_interest"
        elif popularity_score > 0:
            reason = "tenant_popularity"
        else:
            reason = "eligible_catalog_fallback"
        scored_items.append({
            "product_id": product.id,
            "sku": product.sku,
            "name": product.name,
            "price": float(product.price or 0),
            "score": round(score, 6),
            "reason": reason,
        })
    scored_items.sort(key=lambda item: (-item["score"], item["product_id"]))
    served_items = scored_items[:payload.limit]
    model_versions = [MODEL_VERSION]
    if ncf_scores:
        model_versions.append("ncf_bpr_uci_demo")
    if linucb_scores:
        model_versions.append("linucb_uci_demo")
    row = RecommendationRequest(
        business_id=business_id,
        request_id=str(uuid4()),
        customer_id=customer.id if customer else None,
        experiment_id=payload.experiment_id,
        bandit_decision_id=bandit_decision_id,
        strategy=strategy,
        model_version="+".join(model_versions),
        context={
            **payload.context,
            "query": payload.query,
            "rag_candidate_count": len(payload.rag_candidates),
            "eligible_candidate_count": len(scored_items),
            "artifact_segment": artifact_segment,
            "linucb_matched_skus": len(linucb_scores),
            "ncf_matched_skus": len(ncf_scores),
            "customer_interaction_product_count": len(interaction_affinity),
            "historic_interest_token_count": len(historic_tokens),
        },
        served_items=served_items,
    )
    db.add(row)
    db.flush()
    record_recommendation_impressions(db, request=row)
    db.commit()
    db.refresh(row)
    return row


def record_feedback(
    db: Session,
    *,
    business_id: int,
    request_id: str,
    product_id: int,
    event_type: str,
    idempotency_key: str,
    metadata: dict,
) -> RecommendationFeedback:
    existing = db.query(RecommendationFeedback).filter(
        RecommendationFeedback.business_id == business_id,
        RecommendationFeedback.idempotency_key == idempotency_key,
    ).first()
    if existing is not None:
        return existing
    request = db.query(RecommendationRequest).filter(
        RecommendationRequest.business_id == business_id,
        RecommendationRequest.request_id == request_id,
    ).first()
    if request is None:
        raise RecommendationServiceError("Lần gợi ý không tồn tại trong shop này.", 404)
    served_ids = {int(item.get("product_id")) for item in (request.served_items or [])}
    if product_id not in served_ids:
        raise RecommendationServiceError("Sản phẩm không thuộc lần gợi ý này.", 409)
    reward = REWARDS[event_type]
    row = RecommendationFeedback(
        business_id=business_id,
        recommendation_request_id=request.id,
        product_id=product_id,
        event_type=event_type,
        reward=reward,
        idempotency_key=idempotency_key,
        event_metadata=metadata or {},
    )
    db.add(row)
    record_interaction(
        db,
        business_id=business_id,
        customer_id=request.customer_id,
        product_id=product_id,
        request_id=request.request_id,
        event_type=event_type,
        source="recommendation",
        query=None,
        idempotency_key=f"recommendation-feedback:{idempotency_key}",
        metadata=metadata,
        occurred_at=None,
    )
    if event_type in TERMINAL_REWARD_EVENTS and request.bandit_decision_id is not None:
        decision = db.get(BanditDecision, request.bandit_decision_id)
        if decision is not None and decision.reward is None:
            decision.reward = reward
            decision.reward_idempotency_key = idempotency_key
            if decision.policy_id is not None:
                context_hash = decision.context_hash or _context_hash(decision.context)
                stat = db.query(BanditArmStat).filter(
                    BanditArmStat.policy_id == decision.policy_id,
                    BanditArmStat.arm == decision.arm,
                    BanditArmStat.context_hash == context_hash,
                ).first()
                if stat is None:
                    stat = BanditArmStat(
                        business_id=business_id,
                        policy_id=decision.policy_id,
                        arm=decision.arm,
                        context_hash=context_hash,
                        pulls=0,
                        reward_sum=Decimal("0"),
                    )
                    db.add(stat)
                stat.pulls = int(stat.pulls or 0) + 1
                stat.reward_sum = Decimal(stat.reward_sum or 0) + reward
    db.commit()
    db.refresh(row)
    return row


def _kmeans(vectors: list[list[float]], k: int, iterations: int = 25) -> list[int]:
    if not vectors:
        return []
    centers = [list(vector) for vector in vectors[:k]]
    labels = [0] * len(vectors)
    for _ in range(iterations):
        changed = False
        groups: defaultdict[int, list[list[float]]] = defaultdict(list)
        for index, vector in enumerate(vectors):
            label = min(range(k), key=lambda center: sum((value - centers[center][position]) ** 2 for position, value in enumerate(vector)))
            changed = changed or labels[index] != label
            labels[index] = label
            groups[label].append(vector)
        for label, group in groups.items():
            centers[label] = [sum(vector[position] for vector in group) / len(group) for position in range(len(group[0]))]
        if not changed:
            break
    return labels


def train_customer_segments(db: Session, *, business_id: int, training_run_id: int) -> RecommendationTrainingRun:
    run = db.query(RecommendationTrainingRun).filter(
        RecommendationTrainingRun.id == training_run_id,
        RecommendationTrainingRun.business_id == business_id,
    ).first()
    if run is None:
        raise RecommendationServiceError("Training run không tồn tại.", 404)
    run.status, run.started_at, run.error_message = "running", _now(), None
    db.commit()
    try:
        customers = db.query(Customer).filter(Customer.business_id == business_id, Customer.status != "merged").order_by(Customer.id.asc()).all()
        orders = db.query(Order).filter(
            Order.business_id == business_id,
            Order.status.in_(REVENUE_ORDER_STATUSES),
        ).all()
        by_customer: defaultdict[int, list[Order]] = defaultdict(list)
        for order in orders:
            by_customer[int(order.customer_id)].append(order)
        now = _now()
        item_rows = db.query(Order.customer_id, OrderItem.product_id, OrderItem.quantity).join(
            Order, Order.id == OrderItem.order_id
        ).filter(
            Order.business_id == business_id,
            Order.status.in_(REVENUE_ORDER_STATUSES),
        ).all()
        items_by_customer: defaultdict[int, list[tuple[int, int]]] = defaultdict(list)
        for customer_id, product_id, quantity in item_rows:
            if customer_id is not None:
                items_by_customer[int(customer_id)].append((int(product_id), int(quantity or 0)))
        profiles = []
        for customer in customers:
            customer_orders = by_customer.get(customer.id, [])
            latest = max((order.created_at for order in customer_orders if order.created_at), default=None)
            customer_items = items_by_customer.get(customer.id, [])
            monetary = float(sum((Decimal(order.total_amount or 0) for order in customer_orders), Decimal("0")))
            profiles.append({
                "customer_id": customer.id,
                "recency_days": (now - latest).days if latest else 365,
                "frequency": len(customer_orders),
                "monetary": monetary,
                "total_items": sum(quantity for _, quantity in customer_items),
                "distinct_products": len({product_id for product_id, _ in customer_items}),
                "avg_order_value": monetary / max(1, len(customer_orders)),
            })
        if not profiles:
            run.status, run.metrics, run.artifact, run.completed_at = "succeeded", {"customers": 0, "clusters": 0}, {"model_version": SEGMENT_MODEL_VERSION}, _now()
            db.commit()
            return run
        try:
            labels = [artifact_registry.demo_segmentation_label(profile) for profile in profiles]
        except RecommendationArtifactError:
            labels = []
        use_imported_model = len(labels) == len(profiles) and all(label is not None for label in labels)
        if use_imported_model:
            labels = [int(label) for label in labels]
            cluster_count = len(set(labels))
            profile_model_version = "uci_kmeans_demo_v1"
            algorithm = "imported_uci_kmeans"
        else:
            raw = [[float(profile["recency_days"]), float(profile["frequency"]), float(profile["monetary"])] for profile in profiles]
            means = [sum(vector[index] for vector in raw) / len(raw) for index in range(3)]
            deviations = [math.sqrt(sum((vector[index] - means[index]) ** 2 for vector in raw) / len(raw)) or 1.0 for index in range(3)]
            normalized = [[(vector[index] - means[index]) / deviations[index] for index in range(3)] for vector in raw]
            cluster_count = min(4, len(profiles))
            labels = _kmeans(normalized, cluster_count)
            profile_model_version = SEGMENT_MODEL_VERSION
            algorithm = "deterministic_rfm_kmeans"
        for profile, label in zip(profiles, labels):
            row = db.query(RecommendationCustomerProfile).filter(
                RecommendationCustomerProfile.business_id == business_id,
                RecommendationCustomerProfile.customer_id == profile["customer_id"],
            ).first()
            values = {
                "segment_label": f"{'uci_cluster' if use_imported_model else 'cluster'}_{label}",
                "features": {key: profile[key] for key in ("recency_days", "frequency", "monetary", "total_items", "distinct_products", "avg_order_value")},
                "model_version": profile_model_version,
                "trained_at": _now(),
            }
            if row is None:
                db.add(RecommendationCustomerProfile(business_id=business_id, customer_id=profile["customer_id"], **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        run.status = "succeeded"
        run.metrics = {"customers": len(profiles), "clusters": cluster_count, "orders": len(orders)}
        run.artifact = {"model_version": profile_model_version, "algorithm": algorithm}
        run.completed_at = _now()
        db.commit()
    except Exception as exc:
        db.rollback()
        run = db.get(RecommendationTrainingRun, training_run_id)
        if run is not None:
            run.status, run.error_message, run.completed_at = "failed", str(exc)[:500], _now()
            db.commit()
        raise
    return run
