"""Recommendation pipeline: source -> filter -> scorer -> selector -> feedback."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import random
import re
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import median
from uuid import uuid4
from urllib.parse import urlsplit

import numpy as np
from sklearn.cluster import MiniBatchKMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.customer import Customer
from app.models.customer_collection import CustomerConsent
from app.models.customer_fact import CustomerFact
from app.models.experimentation import BanditArmStat, BanditDecision, BanditPolicy, Experiment
from app.models.recommendation import (
    RecommendationCustomerProfile,
    RecommendationFeedback,
    RecommendationRequest,
    RecommendationTrainingRun,
    CustomerProductInteraction,
)
from app.models.recommendation_quality_gate import RecommendationShopModelState
from app.models.sales import Order, OrderItem, Product
from app.rag.catalog_filters import attribute_key_aliases, attribute_value_aliases
from app.schemas.recommendation import RagCandidate, RecommendationRequestCreate
from app.services.recommendation_artifacts import RecommendationArtifactError, registry as artifact_registry
from app.services.recommendation_artifacts import stated_budget
from app.services.industry_rfm_prior import (
    INDUSTRY_RFM_PRIOR_VERSION,
    IndustryRfmPriorUnavailable,
    predict_industry_rfm_prior,
    semantic_labels_for_centers,
)
from app.services.recommendation_learning import (
    LIGHTFM_ALGORITHM,
    LIVE_RERANKER_ALGORITHM,
    LIVE_RERANKER_BLEND_VERSION,
    blend_candidate_scores,
    lightfm_customer_key,
    live_reranker_blend_profile,
    score_candidate as score_live_candidate,
    score_lightfm_candidate,
)
from app.rag.topics import fold_topic_text
from app.services.customer_fact_extractor import get_customer_fact_extraction_enabled
from app.services.recommendation_interaction_service import (
    apply_recommendation_outcome,
    record_interaction,
    record_recommendation_impressions,
)
from app.services.order_metrics import completed_order_conditions, net_order_value
from app.tenancy.workspace_modules import get_workspace_config
from app.services.rfm_segments import (
    RFM_CLUSTER_ALGORITHM,
    RFM_CLUSTER_MODEL_VERSION,
    RFM_SEGMENT_KEYS,
    RFM_RULES_VERSION,
    customer_rfm_profiles,
)


REVENUE_ORDER_STATUSES = ("delivered", "completed")
MODEL_VERSION = "item_affinity_rfm_v5"
PERSONALIZATION_CACHE_VERSION = "rfm_product_signals_v2_industry_prior"
SEGMENT_MODEL_VERSION = RFM_CLUSTER_MODEL_VERSION
SEGMENT_ALGORITHM = RFM_CLUSTER_ALGORITHM
RFM_CLUSTER_RANDOM_STATE = 20261101
MIN_SEGMENT_CUSTOMERS = 20
STRATEGIES = {"balanced", "personalized", "popular", "rag"}
MIN_BANDIT_TRAINING_EVENTS = 50
INTERACTION_WEIGHTS = {
    "view": 0.05,
    "impression": 0.0,
    "click": 0.25,
    "cart": 0.60,
    "checkout_intent": 0.25,
    "purchase": 1.0,
    "skip": -0.35,
    "refund": -1.0,
}
INTERACTION_HALF_LIFE_DAYS = 45
PRODUCT_COLOR_ALIASES = {
    "pink": ("pink", "hồng", "rose", "rosy", "fuchsia", "magenta"),
    "red": ("red", "đỏ"),
    "blue": ("blue", "xanh dương", "xanh lam", "navy"),
    "green": ("green", "xanh lá", "xanh lục"),
    "black": ("black", "đen", "den"),
    "white": ("white", "trắng", "trang", "ivory"),
    "yellow": ("yellow", "vàng", "vang"),
    "purple": ("purple", "tím", "tim", "violet"),
    "brown": ("brown", "nâu", "nau"),
    "gray": ("gray", "grey", "xám", "xam"),
}
PURCHASE_FACET_KEYS = {
    "category": ("category", "product_category", "danh_muc"),
    "brand": ("brand", "product_brand", "manufacturer", "thuong_hieu"),
    "product_type": ("product_type", "product_group", "type", "loai_san_pham"),
    "tags": ("tags", "tag", "labels", "nhan"),
    "style": ("style", "collection", "phong_cach", "bo_suu_tap"),
    "material": ("material", "chat_lieu"),
    "color": ("color", "colors", "colour", "colours", "mau", "mau_sac"),
}
PURCHASE_FACET_WEIGHTS = {
    "category": 1.0,
    "brand": 0.9,
    "product_type": 0.9,
    "tags": 0.75,
    "style": 0.75,
    "material": 0.65,
    "color": 0.65,
}


class RecommendationServiceError(ValueError):
    def __init__(self, detail: str, status_code: int = 422):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _require_clean_read_only_session(db: Session, *, persist: bool) -> None:
    """Prevent offline evaluation queries from flushing caller-owned writes."""
    if not persist and (db.new or db.dirty or db.deleted):
        raise RecommendationServiceError(
            "Offline recommendation evaluation requires a clean database session.", 409,
        )


def _active_live_feedback_reranker(db: Session, business_id: int) -> tuple[dict | None, int | None]:
    try:
        with db.begin_nested():
            state = db.query(RecommendationShopModelState).filter(
                RecommendationShopModelState.business_id == business_id,
            ).one_or_none()
            supported_algorithms = {LIVE_RERANKER_ALGORITHM, LIGHTFM_ALGORITHM}
            if state is None or not state.enabled or state.gate_status != "passed" or state.algorithm not in supported_algorithms:
                return None, None
            state_metrics = state.metrics if isinstance(state.metrics, dict) else {}
            try:
                training_run_id = int(state_metrics.get("active_training_run_id"))
            except (TypeError, ValueError):
                return None, None
            run = db.query(RecommendationTrainingRun).filter(
                RecommendationTrainingRun.id == training_run_id,
                RecommendationTrainingRun.business_id == business_id,
                RecommendationTrainingRun.algorithm == state.algorithm,
                RecommendationTrainingRun.status == "succeeded",
            ).first()
    except SQLAlchemyError:
        # Until the tenant migration is applied, ranking remains on baseline.
        return None, None
    artifact = run.artifact if run and isinstance(run.artifact, dict) else {}
    artifact_algorithm = artifact.get("algorithm")
    if artifact_algorithm is None and state.algorithm == LIVE_RERANKER_ALGORITHM:
        artifact_algorithm = LIVE_RERANKER_ALGORITHM if str(artifact.get("model_version") or "").startswith(LIVE_RERANKER_ALGORITHM) else None
    if (
        run is None
        or artifact_algorithm != state.algorithm
        or artifact.get("serving_enabled") is not True
        or artifact.get("model_version") != state.model_version
    ):
        return None, None
    return artifact, int(run.id)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _completed_order_conditions():
    return completed_order_conditions(_now())


def _customer_product_signal_conditions():
    """Use non-cancelled orders as product-interest signals, independent of full payment."""
    return (
        Order.status.in_(("confirmed", "processing", "shipped", "delivered", "completed")),
        Order.payment_status.notin_(("refunded", "failed")),
        Order.total_amount > Order.refunded_amount,
        Order.created_at <= _now(),
    )


def _net_order_value(order: Order) -> Decimal:
    return net_order_value(order)


def _context_hash(context: dict) -> str:
    encoded = json.dumps(context or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _recommendation_click_secret() -> bytes:
    configured = str(settings.CHANNEL_ENCRYPTION_KEY or "").strip()
    return (configured or f"{settings.APP_NAME}:recommendation-click").encode("utf-8")


def recommendation_click_signature(
    *, business_id: int, request_id: str, product_id: int, expires: int
) -> str:
    payload = f"{int(business_id)}:{request_id}:{int(product_id)}:{int(expires)}".encode("utf-8")
    return hmac.new(_recommendation_click_secret(), payload, hashlib.sha256).hexdigest()


def verify_recommendation_click_signature(
    *, business_id: int, request_id: str, product_id: int, expires: int, signature: str
) -> bool:
    if int(expires) < int(time.time()):
        return False
    expected = recommendation_click_signature(
        business_id=business_id,
        request_id=request_id,
        product_id=product_id,
        expires=expires,
    )
    return hmac.compare_digest(str(signature or ""), expected)


def _recommendation_click_url(*, business_id: int, request_id: str, product_id: int) -> str | None:
    base = str(settings.PUBLIC_BASE_URL or "").strip().rstrip("/")
    if not base:
        return None
    expires = int(time.time()) + 365 * 24 * 60 * 60
    signature = recommendation_click_signature(
        business_id=business_id,
        request_id=request_id,
        product_id=product_id,
        expires=expires,
    )
    return f"{base}/api/recommendations/click/{business_id}/{request_id}/{product_id}?expires={expires}&signature={signature}"


def active_recommendation_experiment_id(db: Session, *, business_id: int) -> int | None:
    """Return an explicitly running recommendation experiment, if configured."""
    rows = db.query(Experiment, BanditPolicy).join(
        BanditPolicy, BanditPolicy.experiment_id == Experiment.id,
    ).filter(
        Experiment.business_id == business_id,
        Experiment.status == "running",
        BanditPolicy.business_id == business_id,
        BanditPolicy.status == "active",
    ).order_by(Experiment.id.desc(), BanditPolicy.id.desc()).all()
    for experiment, policy in rows:
        config = policy.config if isinstance(policy.config, dict) else {}
        if config.get("runtime_binding") not in (None, "recommendation_strategy"):
            continue
        variants = [str(value).strip() for value in (experiment.variants or [])]
        if variants and all(value in STRATEGIES for value in variants):
            return int(experiment.id)
    return None


def safe_http_url(value: object) -> str | None:
    text = str(value or "").strip()
    try:
        parsed = urlsplit(text)
        if parsed.scheme.lower() in {"http", "https"} and parsed.hostname and parsed.username is None and parsed.password is None:
            return text
    except ValueError:
        pass
    return None


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
    context: dict | None = None,
) -> tuple[str, int | None, dict]:
    if payload.experiment_id is None:
        return "balanced", None, {
            "policy": "deterministic",
            "selection_reason": "no_experiment",
            "selection_probability": 1.0,
        }
    experiment = db.query(Experiment).filter(
        Experiment.id == payload.experiment_id,
        Experiment.business_id == business_id,
    ).first()
    if experiment is None:
        raise RecommendationServiceError("Experiment không tồn tại trong shop này.", 404)
    if experiment.status != "running":
        raise RecommendationServiceError("Experiment recommendation phải ở trạng thái running.", 409)
    variants = list(dict.fromkeys(str(item).strip() for item in (experiment.variants or [])))
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
            epsilon=Decimal("0.02"),
            config={"objective": "terminal_conversion_reward", "min_training_events": MIN_BANDIT_TRAINING_EVENTS},
            status="active",
        )
        db.add(policy)
        db.flush()
    context = context if context is not None else payload.context
    context_hash = _context_hash(context)
    stats = {
        arm: db.query(BanditArmStat).filter(
            BanditArmStat.policy_id == policy.id,
            BanditArmStat.arm == arm,
            BanditArmStat.context_hash == context_hash,
        ).first()
        for arm in variants
    }
    observed_outcomes = int(db.query(func.coalesce(func.sum(BanditArmStat.pulls), 0)).filter(
        BanditArmStat.policy_id == policy.id,
    ).scalar() or 0)
    try:
        minimum_events = max(MIN_BANDIT_TRAINING_EVENTS, min(10000, int(
            (policy.config or {}).get("min_training_events", MIN_BANDIT_TRAINING_EVENTS)
        )))
    except (AttributeError, TypeError, ValueError):
        minimum_events = MIN_BANDIT_TRAINING_EVENTS
    if observed_outcomes < minimum_events:
        # Keep the experiment on its first declared variant until enough
        # terminal outcomes exist; impressions/clicks alone are not rewards.
        strategy, reason = variants[0], "warmup_default"
        selection_probability = 1.0
        applied_epsilon = 0.0
    else:
        epsilon = min(0.05, max(0.0, float(policy.epsilon)))
        if not any(stat and stat.pulls for stat in stats.values()):
            strategy, reason = variants[0], "context_warmup_default"
            selection_probability = 1.0
            applied_epsilon = 0.0
        else:
            applied_epsilon = epsilon
            observed_arms = [arm for arm in variants if stats[arm] and stats[arm].pulls]
            greedy_strategy = max(observed_arms, key=lambda arm: (
                float(((stats[arm].reward_sum or 0) / max(1, stats[arm].pulls)) if stats[arm] else 0),
                arm,
            ))
            if random.random() < epsilon:
                strategy, reason = random.choice(variants), "exploration"
            else:
                strategy, reason = greedy_strategy, "exploitation"
            selection_probability = epsilon / len(variants)
            if strategy == greedy_strategy:
                selection_probability += 1.0 - epsilon
    selection = {
        "policy": "epsilon_greedy_strategy_v1" if payload.experiment_id is not None else "deterministic",
        "selection_reason": reason,
        "selection_probability": round(float(selection_probability), 8),
        "epsilon": applied_epsilon,
        "available_strategies": variants,
        "observed_terminal_outcomes": observed_outcomes,
        "warmup_minimum": minimum_events,
    }
    decision_context = {**(context or payload.context or {}), "_strategy_selection": selection}
    decision = BanditDecision(
        business_id=business_id,
        experiment_id=experiment.id,
        subject_key=subject_key,
        arm=strategy,
        context=decision_context,
        policy_id=policy.id,
        policy_version=policy.version,
        context_hash=context_hash,
        selection_reason=reason,
    )
    db.add(decision)
    db.flush()
    return strategy, decision.id, selection


def _recent_and_historical_products(db: Session, business_id: int, customer_id: int | None) -> tuple[set[int], set[int]]:
    if customer_id is None:
        return set(), set()
    base = db.query(OrderItem.product_id, Order.created_at).join(Order, Order.id == OrderItem.order_id).filter(
        Order.business_id == business_id,
        Order.customer_id == customer_id,
        *_customer_product_signal_conditions(),
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
        *_completed_order_conditions(),
    ).all()
    order_ids = [order.id for order in orders]
    item_rows = []
    if order_ids:
        item_rows = db.query(OrderItem.product_id, OrderItem.quantity).filter(OrderItem.order_id.in_(order_ids)).all()
    latest = max((order.created_at for order in orders if order.created_at), default=None)
    monetary = float(sum((_net_order_value(order) for order in orders), Decimal("0")))
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
        *_completed_order_conditions(),
        OrderItem.product_id.in_(historical_products),
    )
    rows = db.query(OrderItem.product_id, func.count(OrderItem.id)).filter(
        OrderItem.order_id.in_(related_order_ids),
    ).group_by(OrderItem.product_id).all()
    return Counter({int(product_id): int(count) for product_id, count in rows})


def _facets_from_metadata(metadata: object) -> dict[str, set[str]]:
    metadata = metadata if isinstance(metadata, dict) else {}
    facets: dict[str, set[str]] = {}
    for facet, aliases in PURCHASE_FACET_KEYS.items():
        values = []
        for key in aliases:
            value = metadata.get(key)
            values.extend(value if isinstance(value, (list, tuple, set)) else [value])
        normalized = {
            fold_topic_text(" ".join(str(value).split()))
            for value in values
            if isinstance(value, (str, int, float)) and str(value).strip()
        }
        normalized.discard("")
        if normalized:
            facets[facet] = normalized
    return facets


def _product_facets(product: Product) -> dict[str, set[str]]:
    facets = _facets_from_metadata(product.metadata_)
    if "category" not in facets:
        match = re.search(r"\bthuộc\s+nhóm\s+([^;,.]+)", product.description or "", re.IGNORECASE)
        if match:
            category = fold_topic_text(match.group(1).strip())
            if category:
                facets["category"] = {category}
    return facets


def _customer_purchase_facets(db: Session, business_id: int, customer_id: int | None) -> dict[str, Counter]:
    """Learn product attributes from completed orders without asking customers to type them."""
    if customer_id is None:
        return {}
    rows = db.query(OrderItem.quantity, Order.created_at, Product).join(
        Order, Order.id == OrderItem.order_id,
    ).join(
        Product, Product.id == OrderItem.product_id,
    ).filter(
        Order.business_id == business_id,
        Order.customer_id == customer_id,
        Product.business_id == business_id,
        *_customer_product_signal_conditions(),
    ).order_by(Order.created_at.desc()).limit(1000).all()
    profile: dict[str, Counter] = defaultdict(Counter)
    now = _now()
    for quantity, created_at, product in rows:
        days_old = max(0, (now - created_at).days) if created_at else 180
        recency_weight = 0.5 ** (days_old / 180)
        try:
            quantity_weight = min(5, max(1, int(quantity or 1)))
        except (TypeError, ValueError):
            quantity_weight = 1
        for facet, values in _product_facets(product).items():
            for value in values:
                profile[facet][value] += recency_weight * quantity_weight
    return profile


def _purchase_facet_affinity(profile: dict[str, Counter], product: Product) -> tuple[float, list[str]]:
    candidate_facets = _product_facets(product)
    matches = []
    for facet, values in candidate_facets.items():
        history = profile.get(facet)
        if not history:
            continue
        matched = sum(history[value] for value in values)
        if matched:
            matches.append((PURCHASE_FACET_WEIGHTS[facet] * min(1.0, matched / max(history.values())), facet))
    if not matches:
        return 0.0, []
    matches.sort(reverse=True)
    score = min(1.0, matches[0][0] + (0.25 * matches[1][0] if len(matches) > 1 else 0.0))
    return score, sorted(facet for _score, facet in matches)


def _popular_counts(db: Session, business_id: int) -> Counter:
    rows = db.query(OrderItem.product_id, func.count(OrderItem.id)).join(Order, Order.id == OrderItem.order_id).filter(
        Order.business_id == business_id,
        *_completed_order_conditions(),
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
        CustomerProductInteraction.occurred_at <= _now(),
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


def _manual_product_interest_scores(
    db: Session,
    *,
    business_id: int,
    customer_id: int | None,
) -> Counter:
    """Return decayed, staff-recorded interest scores without pooling customers."""
    if customer_id is None:
        return Counter()
    rows = db.query(
        CustomerProductInteraction.product_id,
        CustomerProductInteraction.occurred_at,
        CustomerProductInteraction.event_metadata,
    ).filter(
        CustomerProductInteraction.business_id == business_id,
        CustomerProductInteraction.customer_id == customer_id,
        CustomerProductInteraction.product_id.is_not(None),
        CustomerProductInteraction.event_type == "staff_interest",
        CustomerProductInteraction.occurred_at <= _now(),
    ).order_by(CustomerProductInteraction.occurred_at.desc(), CustomerProductInteraction.id.desc()).all()
    scores: Counter = Counter()
    seen: set[int] = set()
    now = _now()
    for product_id, occurred_at, metadata in rows:
        if int(product_id) in seen:
            continue
        seen.add(int(product_id))
        try:
            interest = min(100.0, max(0.0, float((metadata or {}).get("interest_percent", 0)))) / 100
        except (TypeError, ValueError):
            continue
        days_old = max(0, (now - occurred_at).days) if occurred_at else INTERACTION_HALF_LIFE_DAYS
        decayed_interest = interest * (0.5 ** (days_old / INTERACTION_HALF_LIFE_DAYS))
        scores[int(product_id)] = decayed_interest
    return scores


def _historic_query_tokens(db: Session, business_id: int, customer_id: int | None) -> Counter:
    if customer_id is None:
        return Counter()
    rows = db.query(CustomerProductInteraction.query_text).filter(
        CustomerProductInteraction.business_id == business_id,
        CustomerProductInteraction.customer_id == customer_id,
        CustomerProductInteraction.event_type.in_(("ask", "search")),
        CustomerProductInteraction.query_text.is_not(None),
        CustomerProductInteraction.occurred_at <= _now(),
    ).order_by(CustomerProductInteraction.occurred_at.desc()).limit(100).all()
    return Counter(token for (query,) in rows for token in _tokens(query or ""))


def _tokens(value: str) -> list[str]:
    return [token for token in re.findall(r"\w+", value.lower()) if len(token) > 1]


def _catalog_attribute_text(product: Product) -> str:
    metadata = product.metadata_ if isinstance(product.metadata_, dict) else {}
    keys = {
        "category", "category_name", "product_category", "danh_muc", "danh_mục",
        "product_type", "product_group", "type", "loai_san_pham", "loại_sản_phẩm",
        "brand", "brand_name", "manufacturer", "thuong_hieu", "thương_hiệu",
        "model", "model_name", "compatible_with", "compatible_models", "compatibility",
        "vehicle_compatibility", "fitment", "suitable_for", "use_case", "usage", "service_type",
        "tags", "keywords", "aliases", "search_terms", "features", "specifications",
        "color", "colors", "colour", "colours", "mau", "mau_sac", "màu_sắc",
        "size", "sizes", "style", "collection", "material", "chat_lieu", "chất_liệu",
        "attributes", "product_attributes", "specs", "dietary", "ingredients",
        "allergens", "skin_type", "expiry", "storage",
    }
    values = []
    for key, value in metadata.items():
        if str(key).strip().casefold() not in keys:
            continue
        pending = [value]
        while pending and len(values) < 64:
            item = pending.pop()
            if isinstance(item, dict):
                pending.extend(item.values())
            elif isinstance(item, (list, tuple, set)):
                pending.extend(item)
            elif isinstance(item, (str, int, float)):
                values.append(str(item))
    return " ".join(values)


def _catalog_attribute_overlap(query: str | None, product: Product) -> float:
    query_tokens = set(_tokens(fold_topic_text(query or "")))
    if not query_tokens:
        return 0.0
    attributes = set(_tokens(fold_topic_text(_catalog_attribute_text(product))))
    return len(query_tokens & attributes) / len(query_tokens)


def _query_overlap(query: str | None, product: Product) -> float:
    tokens = set(_tokens(fold_topic_text(query or "")))
    if not tokens:
        return 0.0
    searchable = set(_tokens(fold_topic_text(f"{product.name} {product.description or ''}")))
    return sum(token in searchable for token in tokens) / len(tokens)


def _historic_interest_overlap(tokens: Counter, product: Product) -> float:
    if not tokens:
        return 0.0
    product_tokens = set(_tokens(f"{product.name} {product.description or ''}"))
    matched = sum(tokens[token] for token in product_tokens)
    return min(1.0, matched / max(1, max(tokens.values()) * 2))


def _canonical_color(value: str | None) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    for color, aliases in PRODUCT_COLOR_ALIASES.items():
        if any(alias in text for alias in aliases):
            return color
    return text if len(text) <= 30 else None


def _product_color_text(product: Product) -> str:
    metadata = product.metadata_ if isinstance(product.metadata_, dict) else {}
    values = [product.name or "", product.description or ""]
    for key in ("color", "colors", "colour", "colours", "mau", "mau_sac", "available_colors"):
        value = metadata.get(key)
        if isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value)
        elif value is not None:
            values.append(str(value))
    return " ".join(values).lower()


def _product_matches_color(product: Product, color: str | None) -> bool:
    canonical = _canonical_color(color)
    if not canonical:
        return False
    text = _product_color_text(product)
    aliases = PRODUCT_COLOR_ALIASES.get(canonical, (canonical,))
    return any(alias in text for alias in aliases) or canonical in text


def _preferred_color(db: Session, business_id: int, customer_id: int | None) -> tuple[str | None, str | None]:
    if customer_id is None or not _personalization_allowed(db, business_id, customer_id):
        return None, None

    fact = db.query(CustomerFact).filter(
        CustomerFact.business_id == business_id,
        CustomerFact.customer_id == customer_id,
        CustomerFact.fact_type == "preference",
        CustomerFact.fact_key.in_(("preferred_color", "favorite_color", "color")),
        CustomerFact.confidence >= 0.65,
        or_(CustomerFact.valid_from.is_(None), CustomerFact.valid_from <= _now()),
        or_(CustomerFact.valid_until.is_(None), CustomerFact.valid_until > _now()),
    ).order_by(CustomerFact.is_verified.desc(), CustomerFact.updated_at.desc()).first()
    color = fact.fact_value_json if fact is not None else None
    if isinstance(color, str) and len(color.strip()) <= 80:
        canonical = _canonical_color(color)
        if canonical:
            return canonical, "explicit_color_preference"

    # If the customer has purchased a color before but never stated a
    # preference, use that observable catalog signal as a soft ranking boost.
    # No inferred fact is written back to the profile.
    purchased = db.query(Product, func.sum(OrderItem.quantity)).join(
        OrderItem, OrderItem.product_id == Product.id,
    ).join(
        Order, Order.id == OrderItem.order_id,
    ).filter(
        Order.business_id == business_id,
        Order.customer_id == customer_id,
        *_customer_product_signal_conditions(),
        Product.business_id == business_id,
    ).group_by(Product.id).all()
    color_counts: Counter[str] = Counter()
    for product, quantity in purchased:
        text = _product_color_text(product)
        for canonical, aliases in PRODUCT_COLOR_ALIASES.items():
            if any(alias in text for alias in aliases):
                color_counts[canonical] += max(1, int(quantity or 1))
    if color_counts:
        return color_counts.most_common(1)[0][0], "purchased_color_affinity"
    return None, None


def _stated_preference_values(db: Session, business_id: int, customer_id: int | None) -> list[str]:
    if customer_id is None or not _personalization_allowed(db, business_id, customer_id):
        return []
    keys = (
        "interested_category", "preferred_category", "preferred_product_group",
        "preferred_brand", "preferred_size", "preferred_style",
    )
    rows = db.query(CustomerFact.fact_key, CustomerFact.fact_value_json).filter(
        CustomerFact.business_id == business_id,
        CustomerFact.customer_id == customer_id,
        CustomerFact.fact_key.in_(keys),
        CustomerFact.confidence >= 0.65,
        or_(CustomerFact.valid_from.is_(None), CustomerFact.valid_from <= _now()),
        or_(CustomerFact.valid_until.is_(None), CustomerFact.valid_until > _now()),
    ).order_by(
        CustomerFact.is_verified.desc(), CustomerFact.updated_at.desc(), CustomerFact.id.desc(),
    ).all()
    values = {}
    for key, value in rows:
        if key in values or not isinstance(value, str):
            continue
        clean = " ".join(value.split())
        if 1 <= len(clean) <= 80 and not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", clean):
            values[key] = clean
    return list(values.values())


def _stated_preference_overlap(values: list[str], product: Product) -> float:
    metadata = product.metadata_ if isinstance(product.metadata_, dict) else {}
    product_text = fold_topic_text(
        f"{product.name} {product.description or ''} {metadata}"
    )
    product_tokens = set(_tokens(product_text))
    scores = []
    for value in values:
        tokens = set(_tokens(fold_topic_text(value)))
        if tokens:
            scores.append(len(tokens & product_tokens) / len(tokens))
    return max(scores, default=0.0)


def _personalization_allowed(db: Session, business_id: int, customer_id: int | None) -> bool:
    if customer_id is None or not get_customer_fact_extraction_enabled(db, business_id):
        return False
    customer = db.query(Customer.id).filter(
        Customer.id == customer_id,
        Customer.business_id == business_id,
        Customer.fact_extraction_opt_out.is_(False),
    ).first()
    if customer is None:
        return False
    consent = db.query(CustomerConsent).filter(
        CustomerConsent.business_id == business_id,
        CustomerConsent.customer_id == customer_id,
        CustomerConsent.purpose == "personalization",
    ).order_by(CustomerConsent.id.desc()).first()
    return consent is not None and consent.status == "granted"


def rag_personalization_weights(
    db: Session, *, business_id: int, customer_id: int | None,
) -> dict[str, float] | None:
    """Return saved, consented customer/product weights for RAG's PPR seed."""
    if not _personalization_allowed(db, business_id, customer_id):
        return None
    profile = db.query(RecommendationCustomerProfile).filter(
        RecommendationCustomerProfile.business_id == business_id,
        RecommendationCustomerProfile.customer_id == customer_id,
    ).first()
    if profile is None:
        return None

    features = profile.features or {}
    signals = (features.get("product_signal_cache") or {}).get("signals") or {}
    rfm = features.get("rfm_scores") or {}

    def rfm_score(key: str) -> float:
        try:
            return min(5.0, max(1.0, float(rfm[key]))) / 5.0
        except (KeyError, TypeError, ValueError):
            return 0.6

    recent_factor = 0.5 + 0.5 * rfm_score("recency")
    repeat_factor = 0.5 + 0.25 * rfm_score("frequency") + 0.25 * rfm_score("monetary")
    engagement_factor = sum(rfm_score(key) for key in ("recency", "frequency", "monetary")) / 3
    product_scores: dict[int, float] = {}
    for product_id in signals.get("recent", ()):
        try:
            product_scores[int(product_id)] = product_scores.get(int(product_id), 0.0) + recent_factor
        except (TypeError, ValueError):
            continue
    for product_id in signals.get("historical", ()):
        try:
            product_scores[int(product_id)] = product_scores.get(int(product_id), 0.0) + repeat_factor
        except (TypeError, ValueError):
            continue

    for signal_name in ("interactions", "staff_interest"):
        raw = signals.get(signal_name) or {}
        values = {}
        for product_id, value in raw.items():
            try:
                score = float(value)
                if score:
                    values[int(product_id)] = score
            except (TypeError, ValueError):
                continue
        maximum = max((abs(value) for value in values.values()), default=0.0)
        if maximum:
            for product_id, score in values.items():
                product_scores[product_id] = product_scores.get(product_id, 0.0) + (
                    score / maximum * engagement_factor
                )

    product_scores = {product_id: max(0.0, score) for product_id, score in product_scores.items()}
    product_scores = {product_id: score for product_id, score in product_scores.items() if score > 0}
    if not product_scores:
        return None
    products = db.query(Product.id, Product.sku).filter(
        Product.business_id == business_id,
        Product.id.in_(product_scores),
    ).all()
    maximum = max(product_scores.values())
    weights: dict[str, float] = {}
    for product_id, sku in products:
        weight = product_scores[int(product_id)] / maximum
        weights[f"id:{product_id}"] = weight
        if sku:
            weights[f"sku:{str(sku).strip().casefold()}"] = weight
    return weights or None


def _filter_query_candidates(products: list[Product], query: str | None) -> list[Product]:
    text = fold_topic_text(query)
    budget = stated_budget(query or "")
    color = next((name for name, aliases in PRODUCT_COLOR_ALIASES.items()
                  if any(f" {fold_topic_text(alias)} " in f" {text} " for alias in aliases)), None)
    categories = {fold_topic_text(str((p.metadata_ or {}).get("category") or "")) for p in products}
    mentioned = {category for category in categories if category and f" {category} " in f" {text} "}
    return [p for p in products
            if (budget is None or float(p.price or 0) <= budget)
            and (color is None or _product_matches_color(p, color))
            and (not mentioned or fold_topic_text(str((p.metadata_ or {}).get("category") or "")) in mentioned)]


def _safe_hard_filters(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, object] = {}
    if value.get("object_type") is not None:
        result["object_type"] = str(value["object_type"]).strip().casefold()
    sku = value.get("sku")
    if sku is not None:
        values = sku if isinstance(sku, (list, tuple, set, frozenset)) else [sku]
        result["sku"] = {
            " ".join(unicodedata.normalize("NFKC", str(item)).casefold().split())
            for item in values if str(item).strip()
        }
    attributes = value.get("required_attributes")
    if isinstance(attributes, dict):
        result["required_attributes"] = {
            unicodedata.normalize("NFKC", str(key)).strip().casefold(): unicodedata.normalize("NFKC", str(expected)).strip().casefold()
            for key, expected in attributes.items() if str(key).strip() and str(expected).strip()
        }
    return result


def _product_matches_hard_filters(product: Product, filters: dict[str, object]) -> bool:
    if not filters:
        return True
    if filters.get("object_type") not in (None, "product"):
        return False
    sku_values = filters.get("sku")
    product_sku = " ".join(unicodedata.normalize("NFKC", str(product.sku)).casefold().split())
    if sku_values and product_sku not in sku_values:
        return False
    required = filters.get("required_attributes")
    if isinstance(required, dict):
        metadata = product.metadata_ if isinstance(product.metadata_, dict) else {}
        attributes = metadata.get("attributes") if isinstance(metadata.get("attributes"), dict) else {}
        normalized_attributes = {
            "_".join(unicodedata.normalize("NFKC", str(name)).casefold().split()): actual
            for source in (metadata, attributes)
            for name, actual in source.items()
        }
        for key, expected in required.items():
            actual = next((
                normalized_attributes["_".join(alias.split())]
                for alias in attribute_key_aliases(str(key), expected)
                if "_".join(alias.split()) in normalized_attributes
            ), None)
            actual_values = actual if isinstance(actual, (list, tuple, set)) else [actual]
            normalized = {
                " ".join(unicodedata.normalize("NFKC", str(item)).casefold().split())
                for item in actual_values if item is not None
            }
            accepted = set(attribute_value_aliases(str(key), expected))
            if not accepted.intersection(normalized):
                return False
    return True


def _product_quality_validation(product: Product, business_id: int, filters: dict[str, object]) -> dict[str, object]:
    available = int(product.stock_quantity or 0) - int(product.reserved_quantity or 0)
    required = filters.get("required_attributes")
    attributes_match = _product_matches_hard_filters(product, {"required_attributes": required}) if required else None
    sku_values = filters.get("sku")
    sku_match = (
        " ".join(unicodedata.normalize("NFKC", str(product.sku)).casefold().split()) in sku_values
        if sku_values else None
    )
    object_type_match = filters.get("object_type") in (None, "product")
    checks = {
        "shop_match": int(product.business_id) == int(business_id),
        "active": product.status == "active",
        "available": available > 0,
        "sku_match": sku_match,
        "object_type_match": object_type_match,
        "required_attributes_match": attributes_match,
    }
    return {
        **checks,
        "required_attribute_count": len(required) if isinstance(required, dict) else 0,
        "compliant": all(value is not False for value in checks.values()),
    }


def _explicit_sku_matches(products: list[Product], query: str | None) -> set[int]:
    text = fold_topic_text(query)
    return {
        product.id for product in products
        if product.sku and re.search(rf"(?<!\w){re.escape(fold_topic_text(product.sku))}(?!\w)", text)
    }


def _recommendation_weights(strategy: str, rfm_segment: str | None = None) -> dict[str, float]:
    weights = {
        "balanced": (0.45, 0.20, 0.30, 0.05),
        "personalized": (0.70, 0.15, 0.10, 0.05),
        "popular": (0.10, 0.75, 0.10, 0.05),
        "rag": (0.20, 0.10, 0.65, 0.05),
    }[strategy]
    # RFM gently changes the balance between customer affinity and broad
    # discovery. It never overrides stock, tenant, consent, or explicit query
    # filters, and unknown segments keep the existing strategy weights.
    multipliers = {
        "high_value": (1.12, 0.92, 1.00, 0.96),
        "loyal": (1.12, 0.92, 1.00, 0.96),
        "potential": (1.00, 0.96, 1.08, 1.08),
        "needs_attention": (1.08, 1.00, 1.00, 1.00),
        "at_risk": (1.08, 1.00, 1.00, 1.00),
        "new_customer": (0.65, 1.12, 1.08, 1.12),
        "no_purchase": (0.65, 1.12, 1.08, 1.12),
    }.get(str(rfm_segment or ""), (1.0, 1.0, 1.0, 1.0))
    adjusted = [weight * multiplier for weight, multiplier in zip(weights, multipliers)]
    total = sum(adjusted) or 1.0
    return dict(zip(("affinity", "popularity", "rag", "query"), (weight / total for weight in adjusted)))


def _score(
    strategy: str,
    affinity: float,
    popularity: float,
    rag: float,
    lexical: float,
    *,
    rfm_segment: str | None = None,
) -> float:
    weights = _recommendation_weights(strategy, rfm_segment)
    return (
        affinity * weights["affinity"]
        + popularity * weights["popularity"]
        + rag * weights["rag"]
        + lexical * weights["query"]
    )


def _consented_rfm_peer_reference(
    db: Session,
    business_id: int,
    profiles: dict[int, dict],
) -> tuple[float | None, int]:
    """Build the cold-start money baseline only from currently consented buyers."""
    if not get_customer_fact_extraction_enabled(db, business_id):
        return None, 0
    consent_rows = db.query(CustomerConsent.customer_id, CustomerConsent.status).filter(
        CustomerConsent.business_id == business_id,
        CustomerConsent.purpose == "personalization",
    ).order_by(CustomerConsent.id.asc()).all()
    latest: dict[int, str] = {}
    for customer_id, status in consent_rows:
        latest[int(customer_id)] = str(status)
    granted_ids = {customer_id for customer_id, status in latest.items() if status == "granted"}
    if not granted_ids:
        return None, 0
    eligible_ids = {
        int(customer_id)
        for (customer_id,) in db.query(Customer.id).filter(
            Customer.business_id == business_id,
            Customer.id.in_(granted_ids),
            Customer.status != "merged",
            Customer.fact_extraction_opt_out.is_(False),
        ).all()
    }
    buyer_spend = [
        max(0.0, float(profiles[customer_id].get("monetary") or 0))
        for customer_id in eligible_ids
        if customer_id in profiles and int(profiles[customer_id].get("frequency") or 0) > 0
    ]
    # A stable median needs several peers. Before that, the prior treats M as
    # neutral and still predicts from R and F rather than learning from one user.
    if len(buyer_spend) < 5:
        return None, len(buyer_spend)
    return float(median(buyer_spend)), len(buyer_spend)


def _active_shop_rfm_segmenter(db: Session, business_id: int) -> dict | None:
    run = db.query(RecommendationTrainingRun).filter(
        RecommendationTrainingRun.business_id == business_id,
        RecommendationTrainingRun.algorithm.in_((SEGMENT_ALGORITHM, "rfm_rules_insufficient_cluster_samples")),
        RecommendationTrainingRun.status == "succeeded",
    ).order_by(RecommendationTrainingRun.id.desc()).first()
    artifact = run.artifact if run and isinstance(run.artifact, dict) else {}
    segmenter = artifact.get("segmenter") if isinstance(artifact.get("segmenter"), dict) else {}
    if (
        segmenter.get("status") != "trained"
        or segmenter.get("model_version") != SEGMENT_MODEL_VERSION
        or segmenter.get("algorithm") != SEGMENT_ALGORITHM
    ):
        return None
    return segmenter


def _predict_shop_rfm_segmenter(segmenter: dict, features: dict) -> dict | None:
    names = segmenter.get("feature_names")
    mean = segmenter.get("scaler_mean")
    scale = segmenter.get("scaler_scale")
    centers = segmenter.get("centers_scaled")
    if (
        names != ["recency_days", "frequency", "monetary"]
        or not isinstance(mean, list) or len(mean) != 3
        or not isinstance(scale, list) or len(scale) != 3
        or not isinstance(centers, list) or not centers
        or any(not isinstance(center, list) or len(center) != 3 for center in centers)
    ):
        return None
    try:
        raw = [math.log1p(max(0.0, float(features[name]))) for name in names]
        normalized = [(value - float(center)) / float(divisor) for value, center, divisor in zip(raw, mean, scale)]
        if any(not math.isfinite(value) for value in normalized) or any(float(value) <= 0 for value in scale):
            return None
        cluster_id = min(
            range(len(centers)),
            key=lambda index: sum((value - float(center)) ** 2 for value, center in zip(normalized, centers[index])),
        )
        label_map = segmenter.get("cluster_segment_labels") or semantic_labels_for_centers(centers)
        label = str(label_map[str(cluster_id)])
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    from app.services.rfm_segments import RFM_SEGMENT_KEYS
    segment_name = next((name for name, key in RFM_SEGMENT_KEYS.items() if key == label), "RFM · Duy trì")
    return {
        "cluster_id": int(cluster_id),
        "cluster_model_version": SEGMENT_MODEL_VERSION,
        "cluster_model_source": "shop_trained",
        "recommendation_segment_label": label,
        "recommendation_segment_name": segment_name,
        "rfm_scores": features.get("rfm_scores"),
        "rfm_model_confidence": "shop_trained",
    }


def _recommendation_rfm_assignment(
    db: Session,
    *,
    business_id: int,
    statistics: dict,
    profiles: dict[int, dict],
) -> dict:
    if int(statistics.get("frequency") or 0) <= 0:
        return {
            "cluster_id": None,
            "cluster_model_version": RFM_RULES_VERSION,
            "cluster_model_source": "no_purchase_rule",
            "recommendation_segment_label": statistics["segment_label"],
            "recommendation_segment_name": statistics["segment_name"],
            "rfm_scores": statistics.get("rfm_scores"),
            "rfm_model_confidence": "no_purchase",
        }
    segmenter = _active_shop_rfm_segmenter(db, business_id)
    if segmenter is not None:
        assignment = _predict_shop_rfm_segmenter(segmenter, statistics)
        if assignment is not None:
            return assignment
    peer_median, peer_count = _consented_rfm_peer_reference(db, business_id, profiles)
    config = get_workspace_config(db, business_id)
    try:
        assignment = predict_industry_rfm_prior(
            statistics,
            industry=config.get("recommendation_industry", "general_retail"),
            peer_median_monetary=peer_median,
            consented_buyer_count=peer_count,
        )
    except IndustryRfmPriorUnavailable:
        assignment = None
    if assignment is not None:
        return assignment
    return {
        "cluster_id": None,
        "cluster_model_version": RFM_RULES_VERSION,
        "cluster_model_source": "rules_artifact_unavailable",
        "recommendation_segment_label": statistics["segment_label"],
        "recommendation_segment_name": statistics["segment_name"],
        "rfm_scores": statistics.get("rfm_scores"),
        "rfm_model_confidence": "fallback_rules",
    }


def _personalization_source_signature(db: Session, business_id: int, customer_id: int) -> str:
    """Cheap aggregates detect changed orders/signals without loading order lines.

    Status/payment groups and sums detect same-second status/refund updates, for
    which timestamp-only invalidation would miss a change. The hourly bucket
    also advances recency, time decay and future-dated event eligibility.
    """
    now = _now()
    orders = db.query(
        Order.customer_id, Order.status, Order.payment_status, func.count(Order.id),
        func.sum(Order.total_amount), func.sum(Order.refunded_amount),
        func.max(Order.updated_at), func.max(Order.created_at),
    ).filter(Order.business_id == business_id, Order.created_at <= now).group_by(
        Order.customer_id, Order.status, Order.payment_status,
    ).order_by(Order.customer_id, Order.status, Order.payment_status).all()
    interactions = db.query(
        func.count(CustomerProductInteraction.id), func.max(CustomerProductInteraction.id),
        func.max(CustomerProductInteraction.occurred_at),
    ).filter(
        CustomerProductInteraction.business_id == business_id,
        CustomerProductInteraction.customer_id == customer_id,
        CustomerProductInteraction.event_type != "impression",
        CustomerProductInteraction.occurred_at <= now,
    ).one()
    catalog = db.query(func.count(Product.id), func.max(Product.updated_at)).filter(
        Product.business_id == business_id,
    ).one()
    customers = db.query(Customer.id).filter(
        Customer.business_id == business_id, Customer.status != "merged",
    ).order_by(Customer.id).all()
    consents = db.query(
        CustomerConsent.customer_id, CustomerConsent.purpose, CustomerConsent.status, CustomerConsent.id,
    ).filter(CustomerConsent.business_id == business_id).order_by(CustomerConsent.id.asc()).all()
    latest_segmenter = db.query(RecommendationTrainingRun.id, RecommendationTrainingRun.completed_at).filter(
        RecommendationTrainingRun.business_id == business_id,
        RecommendationTrainingRun.algorithm.in_((SEGMENT_ALGORITHM, "rfm_rules_insufficient_cluster_samples")),
        RecommendationTrainingRun.status == "succeeded",
    ).order_by(RecommendationTrainingRun.id.desc()).first()
    workspace = get_workspace_config(db, business_id)
    source = [PERSONALIZATION_CACHE_VERSION, RFM_RULES_VERSION, now.strftime("%Y-%m-%dT%H"),
              [list(row) for row in orders], list(interactions), list(catalog), [row[0] for row in customers],
              [list(row) for row in consents], workspace.get("recommendation_industry"),
              list(latest_segmenter) if latest_segmenter else None]
    return hashlib.sha256(json.dumps(source, default=str, ensure_ascii=False).encode()).hexdigest()


def _cached_personalization_profile(
    db: Session, business_id: int, customer_id: int, *, rfm_profiles: dict | None = None,
    persist: bool = True,
) -> tuple[RecommendationCustomerProfile, bool]:
    """Persist deterministic RFM/product preferences; never call an AI provider.

    Caller must enforce current personalization consent before entering here.
    Price, available inventory and explicit customer preferences stay live.
    """
    _require_clean_read_only_session(db, persist=persist)
    customer_query = db.query(Customer.id).filter(
        Customer.business_id == business_id, Customer.id == customer_id,
    )
    (customer_query.with_for_update() if persist else customer_query).one()
    profile = db.query(RecommendationCustomerProfile).filter(
        RecommendationCustomerProfile.business_id == business_id,
        RecommendationCustomerProfile.customer_id == customer_id,
    ).first()
    signature = _personalization_source_signature(db, business_id, customer_id)
    features = dict(profile.features or {}) if profile else {}
    cache = features.get("product_signal_cache") or {}
    if rfm_profiles is None and cache.get("signature") == signature:
        return profile, True
    all_profiles = rfm_profiles if rfm_profiles is not None else customer_rfm_profiles(db, business_id, as_of=_now())
    statistics = all_profiles[customer_id]
    model_assignment = _recommendation_rfm_assignment(
        db,
        business_id=business_id,
        statistics=statistics,
        profiles=all_profiles,
    )
    recent, historical = _recent_and_historical_products(db, business_id, customer_id)
    signals = {
        "recent": sorted(recent), "historical": sorted(historical),
        "purchase_facets": {key: dict(values) for key, values in _customer_purchase_facets(db, business_id, customer_id).items()},
        "interactions": dict(_interaction_scores(db, business_id=business_id, customer_id=customer_id)),
        "staff_interest": dict(_manual_product_interest_scores(db, business_id=business_id, customer_id=customer_id)),
        "historic_tokens": dict(_historic_query_tokens(db, business_id, customer_id)),
    }
    now = _now()
    for key in (
        "cluster_id", "cluster_model_version", "cluster_model_source", "cluster_model_industry",
        "cluster_model_backing", "recommendation_segment_label", "recommendation_segment_name",
        "rfm_model_confidence", "rfm_model_consent_peer_count", "rfm_percentile_scores",
    ):
        features.pop(key, None)
    features.update({
        **statistics, "has_completed_order": statistics["frequency"] > 0,
        "as_of": now.isoformat(), "basis": "all_completed_or_paid_delivered_net_of_refunds",
        "rfm_rules_version": RFM_RULES_VERSION,
        "rfm_percentile_scores": statistics.get("rfm_scores"),
        **model_assignment,
        "product_signal_cache": {"signature": signature, "version": PERSONALIZATION_CACHE_VERSION, "signals": signals},
    })
    if not persist:
        return RecommendationCustomerProfile(
            business_id=business_id,
            customer_id=customer_id,
            features=features,
            segment_label=statistics["segment_label"],
            model_version=RFM_RULES_VERSION,
            trained_at=now,
        ), False
    if profile is None:
        profile = RecommendationCustomerProfile(business_id=business_id, customer_id=customer_id)
        db.add(profile)
    profile.features = features
    profile.segment_label = statistics["segment_label"]
    profile.model_version = RFM_RULES_VERSION
    profile.trained_at = now
    db.flush()
    return profile, False


def _recommendation_segment(profile: RecommendationCustomerProfile | None) -> str | None:
    if profile is None:
        return None
    features = profile.features if isinstance(profile.features, dict) else {}
    return str(features.get("recommendation_segment_label") or profile.segment_label)


def rag_candidates_from_chunks(
    db: Session,
    *,
    business_id: int,
    chunks: list,
) -> tuple[list[RagCandidate], list[dict]]:
    """Map retrieved chunks to this shop's products and keep a content-free score trace."""
    products = db.query(Product.id, Product.sku).filter(Product.business_id == business_id).all()
    owned_ids = {int(product_id) for product_id, _sku in products}
    sku_to_id = {str(sku).strip().casefold(): int(product_id) for product_id, sku in products if sku}
    by_product: dict[int, dict[str, float | int]] = {}
    trace = []
    score_names = ("bm25_score", "vector_score", "rrf_score", "ppr_score")
    rank_names = ("bm25_rank", "vector_rank", "rrf_rank", "ppr_rank", "retrieval_rank")

    for result_rank, chunk in enumerate(chunks[:100], start=1):
        metadata = chunk.metadata if isinstance(getattr(chunk, "metadata", None), dict) else {}
        product_id = None
        try:
            candidate_id = int(metadata.get("product_id"))
            if candidate_id in owned_ids:
                product_id = candidate_id
        except (TypeError, ValueError):
            pass
        if product_id is None and metadata.get("sku"):
            product_id = sku_to_id.get(str(metadata["sku"]).strip().casefold())

        raw_scores = getattr(chunk, "retrieval_scores", {})
        safe_scores = {}
        if isinstance(raw_scores, dict):
            for name in (*score_names, *rank_names):
                value = raw_scores.get(name)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
                    safe_scores[name] = int(value) if name in rank_names else float(value)
        safe_scores["retrieval_rank"] = result_rank
        trace.append({
            "chunk_id": int(chunk.chunk_id),
            "document_id": int(chunk.document_id),
            "product_id": product_id,
            "result_rank": result_rank,
            "scores": safe_scores,
        })
        if product_id is None:
            continue
        product_scores = by_product.setdefault(product_id, {})
        for name in score_names:
            if name in safe_scores:
                current = product_scores.get(name)
                product_scores[name] = max(float(current), safe_scores[name]) if current is not None else safe_scores[name]
        for name in rank_names:
            if name in safe_scores:
                current = product_scores.get(name)
                product_scores[name] = min(int(current), safe_scores[name]) if current is not None else safe_scores[name]

    max_ppr = max((scores.get("ppr_score", 0.0) for scores in by_product.values()), default=0.0)
    max_bm25 = max((scores.get("bm25_score", 0.0) for scores in by_product.values()), default=0.0)
    candidates = []
    for product_id, scores in by_product.items():
        if scores.get("ppr_score") is not None and max_ppr > 0:
            relevance = scores["ppr_score"] / max_ppr
        elif scores.get("vector_score") is not None:
            relevance = min(1.0, max(0.0, scores["vector_score"]))
        else:
            relevance = scores.get("bm25_score", 0.0) / max_bm25 if max_bm25 > 0 else 0.0
        candidates.append(RagCandidate(
            product_id=product_id,
            relevance=min(1.0, max(0.0, relevance)),
            **{name: scores.get(name) for name in score_names},
            **{name: scores.get(name) for name in rank_names},
        ))
    candidates.sort(key=lambda candidate: (-candidate.relevance, candidate.product_id))
    return candidates, trace


def record_catalog_match_recommendation(
    db: Session,
    *,
    business_id: int,
    customer_id: int | None,
    query: str,
    products: list[tuple[int, Product]],
    context: dict,
    rag_candidates: list[RagCandidate] | None = None,
    persist: bool = True,
) -> RecommendationRequest:
    """Persist the safe catalog-matcher fallback using the same exposure contract."""
    _require_clean_read_only_session(db, persist=persist)
    personalized_id = customer_id if _personalization_allowed(db, business_id, customer_id) else None
    profile, _cache_hit = (
        _cached_personalization_profile(db, business_id, personalized_id, persist=persist)
        if personalized_id is not None else (None, False)
    )
    rfm_features = profile.features if profile and isinstance(profile.features, dict) else {}
    rag_by_product = {candidate.product_id: candidate for candidate in rag_candidates or []}
    best_score = max((score for score, _product in products), default=1)
    rfm_segment = _recommendation_segment(profile)
    rfm_model_source = str(rfm_features.get("cluster_model_source") or "")
    rfm_model_eligible = bool(
        personalized_id is not None
        and int(rfm_features.get("frequency") or 0) > 0
        and rfm_model_source in {"industry_prior", "shop_trained"}
    )
    rfm_score_computed = False
    rfm_ranker_applied = False
    rfm_display_order_changed = False
    rfm_tiebreak_scores: dict[int, float] = {}
    rfm_ranking_weights = None
    baseline_products = sorted(products, key=lambda item: (-float(item[0]), int(item[1].id or 0)))
    products = baseline_products
    baseline_display_order = [int(product.id) for _, product in baseline_products[:3]]
    if rfm_model_eligible and len(products) > 1:
        rfm_score_computed = True
        signals = (rfm_features.get("product_signal_cache") or {}).get("signals") or {}
        historical = {int(value) for value in signals.get("historical", []) if str(value).isdigit()}
        co_purchase = _co_purchase_counts(db, business_id, historical)
        popularity = _popular_counts(db, business_id)
        interactions = Counter({int(key): float(value) for key, value in (signals.get("interactions") or {}).items()})
        purchase_facets = {
            str(key): Counter(values)
            for key, values in (signals.get("purchase_facets") or {}).items()
            if isinstance(values, dict)
        }
        max_co_purchase = max(1, max((co_purchase.get(int(product.id), 0) for _, product in products), default=0))
        max_popularity = max(1, max((popularity.get(int(product.id), 0) for _, product in products), default=0))
        max_interaction = max(1.0, max((abs(interactions.get(int(product.id), 0.0)) for _, product in products), default=0.0))
        best_catalog_score = max(1.0, float(best_score))
        rfm_ranking_weights = _recommendation_weights("rag", rfm_segment)
        for match_score, product in products:
            product_id = int(product.id)
            facet_score, _matched_facets = _purchase_facet_affinity(purchase_facets, product)
            co_purchase_score = float(co_purchase.get(product_id, 0) / max_co_purchase)
            interaction_score = max(-1.0, min(1.0, float(interactions.get(product_id, 0.0) / max_interaction)))
            affinity_score = max(-1.0, min(1.0, 0.50 * co_purchase_score + 0.25 * interaction_score + 0.25 * facet_score))
            popularity_score = float(popularity.get(product_id, 0) / max_popularity)
            rag = rag_by_product.get(product_id)
            rag_score = float(rag.relevance) if rag else 0.0
            lexical_score = min(1.0, max(0.0, float(match_score) / best_catalog_score))
            rfm_tiebreak_scores[product_id] = _score(
                "rag", affinity_score, popularity_score, rag_score, lexical_score,
                rfm_segment=rfm_segment,
            )
    products = sorted(
        products,
        key=lambda item: (
            -float(item[0]),
            -rfm_tiebreak_scores.get(int(item[1].id), 0.0),
            int(item[1].id or 0),
        ),
    )
    rfm_display_order_changed = (
        rfm_score_computed
        and [int(product.id) for _, product in products[:3]] != baseline_display_order
    )
    rfm_ranker_applied = rfm_display_order_changed
    candidate_snapshot = []
    request_id = str(uuid4())
    served_items = []
    for rank, (match_score, product) in enumerate(products[:50], start=1):
        rag = rag_by_product.get(int(product.id))
        feature_snapshot = {
            "catalog_match_score": float(match_score),
            "rag_relevance": float(rag.relevance) if rag else None,
            "rag_bm25_score": rag.bm25_score if rag else None,
            "rag_vector_score": rag.vector_score if rag else None,
            "rag_rrf_score": rag.rrf_score if rag else None,
            "rag_ppr_score": rag.ppr_score if rag else None,
            "rag_bm25_rank": rag.bm25_rank if rag else None,
            "rag_vector_rank": rag.vector_rank if rag else None,
            "rag_rrf_rank": rag.rrf_rank if rag else None,
            "rag_ppr_rank": rag.ppr_rank if rag else None,
            "rag_retrieval_rank": rag.retrieval_rank if rag else None,
            "rfm_segment": _recommendation_segment(profile),
            "rfm_model_version": rfm_features.get("cluster_model_version") if profile else None,
            "rfm_model_source": rfm_features.get("cluster_model_source") if profile else None,
            "rfm_model_industry": (rfm_features.get("cluster_model_industry") or rfm_features.get("cluster_model_backing")) if profile else None,
            "rfm_model_backing": rfm_features.get("cluster_model_backing") if profile else None,
            "rfm_model_confidence": rfm_features.get("rfm_model_confidence") if profile else None,
            "rfm_model_consent_peer_count": rfm_features.get("rfm_model_consent_peer_count") if profile else None,
            "rfm_ranker_applied": rfm_ranker_applied,
            "rfm_score_computed": rfm_score_computed,
            "rfm_display_order_changed": rfm_display_order_changed,
            "rfm_tiebreak_score": rfm_tiebreak_scores.get(int(product.id)),
        }
        candidate_snapshot.append({
            "product_id": int(product.id),
            "rank": rank,
            "score": round(float(match_score) / max(float(best_score), 1.0), 6),
            "feature_snapshot": feature_snapshot,
        })
        if rank > 3:
            continue
        available = max(int(product.stock_quantity or 0) - int(product.reserved_quantity or 0), 0)
        item = {
            "product_id": int(product.id),
            "object_type": "product",
            "recommendation_object_id": str(product.id),
            "catalog_revision": (
                int(product.metadata_.get("recommendation_catalog_revision"))
                if isinstance(product.metadata_, dict)
                and str(product.metadata_.get("recommendation_catalog_revision", "")).isdigit()
                else None
            ),
            "sku": str(product.sku),
            "name": str(product.name),
            "price": float(product.price or 0),
            "available": available,
            "product_url": safe_http_url(getattr(product, "product_url", None)),
            "score": round(float(match_score) / max(float(best_score), 1.0), 6),
            "model_score": None,
            "reason": "catalog_attribute_match",
            "position": rank,
            "selection_probability": None,
            "personalization_signals": ["rfm_segment"] if rfm_score_computed else [],
            "purchase_facets": [],
            "feature_snapshot": feature_snapshot,
        }
        if item["product_url"]:
            item["click_url"] = _recommendation_click_url(
                business_id=business_id,
                request_id=request_id,
                product_id=int(product.id),
            ) or item["product_url"]
        served_items.append(item)

    row = RecommendationRequest(
        business_id=business_id,
        request_id=request_id,
        customer_id=personalized_id,
        experiment_id=None,
        bandit_decision_id=None,
        strategy="catalog_matcher",
        model_version="catalog_matcher_rfm_tiebreak_v1" if rfm_score_computed else "catalog_matcher_v1",
        context={
            **context,
            "traffic_type": str(context.get("traffic_type") or ("live" if persist else "offline_eval"))[:24],
            "query": query if personalized_id is not None else "",
            "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "query_chars": len(query),
            "rfm_segment": _recommendation_segment(profile),
            "rfm_model_version": rfm_features.get("cluster_model_version") if profile else None,
            "rfm_model_source": rfm_features.get("cluster_model_source") if profile else None,
            "rfm_model_industry": (rfm_features.get("cluster_model_industry") or rfm_features.get("cluster_model_backing")) if profile else None,
            "rfm_model_backing": rfm_features.get("cluster_model_backing") if profile else None,
            "rfm_model_confidence": rfm_features.get("rfm_model_confidence") if profile else None,
            "rfm_model_consent_peer_count": rfm_features.get("rfm_model_consent_peer_count") if profile else None,
            "rfm_ranker_applied": rfm_ranker_applied,
            "rfm_score_computed": rfm_score_computed,
            "rfm_display_order_changed": rfm_display_order_changed,
            "rfm_rules_version": RFM_RULES_VERSION if profile else None,
            "rfm_snapshot": {
                key: rfm_features.get(key) for key in ("recency_days", "frequency", "monetary")
            } if profile else None,
            "ranking_weights": {
                "catalog_match_primary": 1.0,
                "rfm_tiebreak": rfm_ranking_weights,
            },
            "eligible_candidate_count": len(products),
            "candidate_snapshot": candidate_snapshot,
            "personalization_applied": rfm_score_computed,
            "personalization_signals": ["rfm_segment"] if rfm_score_computed else [],
            "rfm_model_applied": rfm_score_computed,
            "rfm_ranker_version": "catalog_matcher_rfm_tiebreak_v1" if rfm_score_computed else "catalog_matcher_v1",
            "item_selection_policy": "deterministic_catalog_matcher",
            "item_policy_randomized": False,
            "blend_version": "catalog_matcher_rfm_tiebreak_v1" if rfm_score_computed else "catalog_matcher_v1",
        },
        served_items=served_items,
    )
    if persist:
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def serve_recommendations(
    db: Session,
    *,
    business_id: int,
    payload: RecommendationRequestCreate,
    record_impressions: bool = True,
    persist: bool = True,
) -> RecommendationRequest:
    _require_clean_read_only_session(db, persist=persist)
    started = time.perf_counter()
    source_context = payload.context if isinstance(payload.context, dict) else {}
    hard_filters = _safe_hard_filters(source_context.get("hard_filters"))
    surface = str(source_context.get("surface") or "api")[:40]
    conversation_id = source_context.get("conversation_id")
    try:
        conversation_id = int(conversation_id) if conversation_id is not None else None
    except (TypeError, ValueError):
        conversation_id = None
    retrieval_trace = source_context.get("retrieval_trace")
    safe_retrieval_trace = []
    if isinstance(retrieval_trace, list):
        for trace_position, item in enumerate(retrieval_trace[:100], start=1):
            if not isinstance(item, dict) or not isinstance(item.get("scores"), dict):
                continue
            scores = {
                key: int(value) if key.endswith("_rank") or key == "retrieval_rank" else float(value)
                for key, value in item["scores"].items()
                if key in {"bm25_score", "vector_score", "rrf_score", "ppr_score", "bm25_rank", "vector_rank", "rrf_rank", "ppr_rank", "retrieval_rank"}
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
            }
            try:
                chunk_id, document_id = int(item["chunk_id"]), int(item["document_id"])
                product_id = int(item["product_id"]) if item.get("product_id") is not None else None
                result_rank = int(item.get("result_rank") or trace_position)
            except (KeyError, TypeError, ValueError):
                continue
            if result_rank < 1:
                result_rank = trace_position
            safe_retrieval_trace.append({
                "chunk_id": chunk_id,
                "document_id": document_id,
                "product_id": product_id,
                "result_rank": result_rank,
                "scores": scores,
            })
    raw_diagnostics = source_context.get("retrieval_diagnostics")
    safe_diagnostics = {}
    if isinstance(raw_diagnostics, dict):
        for key, value in raw_diagnostics.items():
            if key not in {
                "retrieval_mode", "retrieval_fallback_stage", "retrieval_error_type",
                "retrieval_fusion", "retrieval_lexical_method", "retrieval_reranker",
                "retrieval_vector_hits", "retrieval_lexical_hits", "retrieval_bm25_hits",
            }:
                continue
            if isinstance(value, str):
                safe_diagnostics[key] = value[:80]
            elif isinstance(value, int) and not isinstance(value, bool):
                safe_diagnostics[key] = value
            elif value is None:
                safe_diagnostics[key] = None
    customer = _customer_or_raise(db, business_id, payload.customer_id)
    personalized_id = customer.id if customer and _personalization_allowed(db, business_id, customer.id) else None
    selection_payload = payload
    if not persist or (customer is not None and personalized_id is None):
        updates = {"experiment_id": None}
        if customer is not None and personalized_id is None:
            updates["context"] = {}
        selection_payload = payload.model_copy(update=updates)
    subject_key = f"customer:{personalized_id}" if personalized_id else "anonymous"
    profile = None
    profile_cache_hit = False
    if personalized_id is not None:
        profile, profile_cache_hit = _cached_personalization_profile(
            db, business_id, personalized_id, persist=persist,
        )
    cached_features = profile.features if profile else {}
    cached_signals = (cached_features.get("product_signal_cache") or {}).get("signals") or {}
    rfm_segment = _recommendation_segment(profile) or "unclassified"
    rfm_model_source = str(cached_features.get("cluster_model_source") or "")
    rfm_model_applied = bool(
        personalized_id is not None
        and int(cached_features.get("frequency") or 0) > 0
        and rfm_model_source in {"industry_prior", "shop_trained"}
    )
    rfm_weights_applied = personalized_id is not None and profile is not None
    rfm_blend_version = (
        "rag_rfm_industry_prior_weights_v1"
        if rfm_model_applied and rfm_model_source == "industry_prior"
        else "rag_rfm_shop_model_weights_v1"
        if rfm_model_applied and rfm_model_source == "shop_trained"
        else "rag_rfm_rule_segment_weights_v1"
        if rfm_weights_applied
        else "rag_product_baseline_v1"
    )
    bandit_context = {
        key: value for key, value in selection_payload.context.items()
        if key not in {"retrieval_trace", "retrieval_diagnostics", "hard_filters"}
    }
    learning_context = {
        **bandit_context,
        "rfm_segment": rfm_segment,
        "rfm_rules_version": RFM_RULES_VERSION,
        "rfm_model_version": cached_features.get("cluster_model_version"),
        "rfm_model_source": cached_features.get("cluster_model_source"),
        "rfm_model_industry": cached_features.get("cluster_model_industry") or cached_features.get("cluster_model_backing"),
        "source_channel": customer.channel,
    } if personalized_id is not None and customer is not None else {}
    strategy, bandit_decision_id, strategy_selection = _select_strategy(
        db,
        business_id=business_id,
        payload=selection_payload,
        subject_key=subject_key,
        context=learning_context,
    )
    ranking_weights = _recommendation_weights(
        strategy,
        rfm_segment if personalized_id is not None else None,
    )
    request_context = {
        **learning_context,
        "ranking_weights": ranking_weights,
        "traffic_type": str(source_context.get("traffic_type") or ("live" if persist else "offline_eval"))[:24],
        "evaluation_run_id": str(source_context.get("evaluation_run_id") or "")[:120] or None,
        "profile_cache_hit": profile_cache_hit,
        "surface": surface,
        "conversation_id": conversation_id,
        "query_hash": hashlib.sha256((payload.query or "").encode("utf-8")).hexdigest(),
        "query_chars": len(payload.query or ""),
        "retrieval_trace": safe_retrieval_trace,
        "retrieval_diagnostics": safe_diagnostics,
        "strategy_selection": strategy_selection,
        "item_selection_policy": "deterministic_ranker",
        "item_policy_randomized": False,
        "blend_version": rfm_blend_version,
        "rfm_ranker_applied": rfm_weights_applied,
        "rfm_model_applied": rfm_model_applied,
        "rfm_ranker_version": rfm_blend_version,
        "behavioral_reranker": None,
    }
    if personalized_id is not None:
        request_context["rfm_snapshot"] = {
            key: cached_features.get(key)
            for key in ("recency_days", "frequency", "monetary")
        }
        request_context["rfm_model_snapshot"] = {
            key: cached_features.get(key)
            for key in (
                "cluster_id", "cluster_model_version", "cluster_model_source",
                "cluster_model_industry", "cluster_model_backing", "recommendation_segment_label",
                "rfm_model_confidence", "rfm_model_consent_peer_count",
            )
        }
    recent, historical = set(cached_signals.get("recent", [])), set(cached_signals.get("historical", []))
    candidates = db.query(Product).filter(
        Product.business_id == business_id,
    ).populate_existing().order_by(Product.id.asc()).all()
    # Recognize an inactive SKU before filtering, so it cannot suggest an unrelated substitute.
    explicit_skus = _explicit_sku_matches(candidates, payload.query)
    candidates = [
        product for product in candidates
        if product.status == "active" and int(product.stock_quantity or 0) > int(product.reserved_quantity or 0)
        and (not explicit_skus or product.id in explicit_skus)
        and (product.id not in recent or product.id in explicit_skus)
    ]
    candidates = _filter_query_candidates(candidates, payload.query)
    candidates = [product for product in candidates if _product_matches_hard_filters(product, hard_filters)]
    data_rag_scores, data_rag_status = {}, "disabled"
    customer_features = (
        {key: float(cached_features[key]) for key in ("recency_days", "frequency", "monetary", "total_items", "distinct_products", "avg_order_value")}
        if profile else _customer_recommendation_features(db, business_id, None)
    )
    artifact_segment, linucb_scores, ncf_scores = _demo_artifact_scores(customer if personalized_id else None, candidates, customer_features)
    popularity = _popular_counts(db, business_id)
    affinity = _co_purchase_counts(db, business_id, historical)
    interaction_affinity = Counter({int(key): value for key, value in cached_signals.get("interactions", {}).items()})
    manual_interest_scores = Counter({int(key): value for key, value in cached_signals.get("staff_interest", {}).items()})
    purchase_facets = {key: Counter(values) for key, values in cached_signals.get("purchase_facets", {}).items()}
    interaction_popularity = _interaction_scores(db, business_id=business_id)
    historic_tokens = Counter(cached_signals.get("historic_tokens", {}))
    preferred_color, color_signal = _preferred_color(db, business_id, personalized_id)
    stated_preferences = _stated_preference_values(db, business_id, personalized_id)
    available_personalization_signals = set()
    if personalized_id is not None:
        if historical:
            available_personalization_signals.add("order_history")
        if any(value != 0 for value in interaction_affinity.values()):
            available_personalization_signals.add("product_interest")
        if any(value > 0 for value in manual_interest_scores.values()):
            available_personalization_signals.add("product_interest")
        if stated_preferences or color_signal == "explicit_color_preference":
            available_personalization_signals.add("stated_preferences")
        if historic_tokens:
            available_personalization_signals.add("past_questions")
        if profile and cached_features.get("frequency", 0) > 0:
            available_personalization_signals.add("rfm_segment")
    rag_candidates_by_product = {candidate.product_id: candidate for candidate in payload.rag_candidates}
    rag_scores = {product_id: candidate.relevance for product_id, candidate in rag_candidates_by_product.items()}
    popularity_signal = Counter(popularity)
    popularity_signal.update(interaction_popularity)
    max_popularity = max(1, max(popularity_signal.values(), default=0))
    max_affinity = max(
        max(affinity.values(), default=0),
        max((abs(value) for value in interaction_affinity.values()), default=0),
        1,
    )
    scored_items = []
    for product in candidates:
        co_purchase_score = float(affinity.get(product.id, 0) / max_affinity)
        interaction_score = float(interaction_affinity.get(product.id, 0) / max_affinity)
        purchase_facet_score, matched_purchase_facets = _purchase_facet_affinity(purchase_facets, product)
        affinity_score = max(-1.0, min(1.0,
            0.50 * co_purchase_score + 0.25 * interaction_score + 0.25 * purchase_facet_score
        ))
        popularity_score = float(popularity_signal.get(product.id, 0) / max_popularity)
        rag_score = float(rag_scores.get(product.id, 0.0))
        current_query_score = _query_overlap(payload.query, product)
        catalog_match_score = _catalog_attribute_overlap(payload.query, product)
        historic_query_score = _historic_interest_overlap(historic_tokens, product)
        lexical_score = max(current_query_score, catalog_match_score, 0.35 * historic_query_score)
        score = _score(
            strategy,
            affinity_score,
            popularity_score,
            rag_score,
            lexical_score,
            rfm_segment=rfm_segment if personalized_id is not None else None,
        )
        color_match = _product_matches_color(product, preferred_color)
        preference_score = _stated_preference_overlap(stated_preferences, product)
        if purchase_facet_score > 0:
            score += 0.18 * purchase_facet_score
        if color_match:
            score += 0.30
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
        elif catalog_match_score > current_query_score:
            reason = "catalog_attribute_match"
        elif color_match:
            reason = color_signal or "color_affinity"
        elif purchase_facet_score > 0:
            reason = (
                "purchase_history_category_affinity"
                if matched_purchase_facets == ["category"]
                else "purchase_history_affinity"
            )
        elif preference_score > 0:
            reason = "stated_preference_affinity"
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
        if preference_score > 0:
            score += 0.20 * preference_score
        item_signals = set()
        if co_purchase_score > 0 or purchase_facet_score > 0 or (color_match and color_signal == "purchased_color_affinity"):
            item_signals.add("order_history")
        if interaction_score > 0:
            item_signals.add("product_interest")
        if preference_score > 0 or (color_match and color_signal == "explicit_color_preference"):
            item_signals.add("stated_preferences")
        if historic_query_score > 0:
            item_signals.add("past_questions")
        if personalized_id is not None and cached_features.get("frequency", 0) > 0:
            item_signals.add("rfm_segment")
        rag_candidate = rag_candidates_by_product.get(int(product.id))
        scored_items.append({
            "product_id": product.id,
            "object_type": "product",
            "recommendation_object_id": str(product.id),
            "catalog_revision": (
                int(product.metadata_.get("recommendation_catalog_revision"))
                if isinstance(product.metadata_, dict)
                and str(product.metadata_.get("recommendation_catalog_revision", "")).isdigit()
                else None
            ),
            "sku": product.sku,
            "name": product.name,
            "price": float(product.price or 0),
            "available": max(int(product.stock_quantity or 0) - int(product.reserved_quantity or 0), 0),
            "product_url": safe_http_url(product.product_url),
            "quality_validation": _product_quality_validation(product, business_id, hard_filters),
            "score": round(score, 6),
            "model_score": round(data_rag_scores[product.id], 6) if product.id in data_rag_scores else None,
            "reason": reason,
            "personalization_signals": sorted(item_signals),
            "purchase_facets": matched_purchase_facets,
            "feature_snapshot": {
                "catalog_match_score": round(catalog_match_score, 6),
                "affinity_score": round(affinity_score, 6),
                "co_purchase_score": round(co_purchase_score, 6),
                "interaction_score": round(interaction_score, 6),
                "purchase_facet_score": round(purchase_facet_score, 6),
                "popularity_score": round(popularity_score, 6),
                "rag_relevance": round(rag_score, 6),
                "rag_bm25_score": rag_candidate.bm25_score if rag_candidate else None,
                "rag_vector_score": rag_candidate.vector_score if rag_candidate else None,
                "rag_rrf_score": rag_candidate.rrf_score if rag_candidate else None,
                "rag_ppr_score": rag_candidate.ppr_score if rag_candidate else None,
                "rag_bm25_rank": rag_candidate.bm25_rank if rag_candidate else None,
                "rag_vector_rank": rag_candidate.vector_rank if rag_candidate else None,
                "rag_rrf_rank": rag_candidate.rrf_rank if rag_candidate else None,
                "rag_ppr_rank": rag_candidate.ppr_rank if rag_candidate else None,
                "rag_retrieval_rank": rag_candidate.retrieval_rank if rag_candidate else None,
                "query_overlap_score": round(current_query_score, 6),
                "historic_query_overlap_score": round(historic_query_score, 6),
                "purchase_facet_affinity": round(purchase_facet_score, 6),
                "stated_preference_score": round(preference_score, 6),
                "color_match": bool(color_match),
                "ncf_score": ncf_score,
                "linucb_score": linucb_score,
                "rfm_segment": rfm_segment if personalized_id is not None else None,
                "rfm_model_version": cached_features.get("cluster_model_version") if personalized_id is not None else None,
                "rfm_model_source": cached_features.get("cluster_model_source") if personalized_id is not None else None,
                "rfm_model_industry": (cached_features.get("cluster_model_industry") or cached_features.get("cluster_model_backing")) if personalized_id is not None else None,
                "rfm_model_backing": cached_features.get("cluster_model_backing") if personalized_id is not None else None,
                "rfm_model_confidence": cached_features.get("rfm_model_confidence") if personalized_id is not None else None,
                "rfm_model_consent_peer_count": cached_features.get("rfm_model_consent_peer_count") if personalized_id is not None else None,
                "rfm_ranker_applied": rfm_weights_applied,
                "rfm_model_applied": rfm_model_applied,
            },
        })
    scored_items.sort(key=lambda item: (-item["score"], item["product_id"]))
    shortlist = scored_items[:3]
    product_map = {product.id: product for product in candidates}
    try:
        data_rag_scores = artifact_registry.data_rag_scores(
            business_id, [product_map[item["product_id"]] for item in shortlist], payload.query
        )
        if data_rag_scores:
            data_rag_status = "ready"
            for item in shortlist:
                item["model_score"] = round(data_rag_scores[item["product_id"]], 6)
                item["score"] = item["model_score"]
                item["reason"] = "data_rag_demo_rerank"
            # Preserve baseline order when the model assigns an equal score.
            shortlist.sort(key=lambda item: -item["score"])
            scored_items = shortlist + scored_items[3:]
    except (RecommendationArtifactError, KeyError, TypeError, ValueError):
        data_rag_scores, data_rag_status = {}, "unavailable"
    for item in scored_items:
        interest_score = float(manual_interest_scores.get(int(item["product_id"]), 0.0))
        if interest_score <= 0:
            continue
        item["score"] = round(float(item["score"]) + 0.30 * interest_score, 6)
        item["staff_interest_percent"] = round(interest_score * 100)
        item["feature_snapshot"]["staff_interest_score"] = round(interest_score, 6)
        item["personalization_signals"] = sorted(set(item["personalization_signals"]) | {"product_interest"})
        if item["reason"] in {"eligible_catalog_fallback", "tenant_popularity"}:
            item["reason"] = "staff_recorded_product_interest"
    scored_items.sort(key=lambda item: (-item["score"], item["product_id"]))
    live_reranker, live_reranker_run_id = _active_live_feedback_reranker(db, business_id)
    if live_reranker is not None:
        reranker_algorithm = str(live_reranker.get("algorithm") or LIVE_RERANKER_ALGORITHM)
        rfm_snapshot = request_context.get("rfm_snapshot")
        scored_items.sort(key=lambda item: (-item["score"], item["product_id"]))
        rerank_pool = scored_items[:50]
        baseline_scores = {
            int(item["product_id"]): float(item["score"])
            for item in rerank_pool
        }
        baseline_ranks = {
            int(item["product_id"]): rank
            for rank, item in enumerate(rerank_pool, start=1)
        }
        model_scores = {}
        for item in rerank_pool:
            product_id = int(item["product_id"])
            rank = baseline_ranks[product_id]
            if reranker_algorithm == LIGHTFM_ALGORITHM:
                customer_key = lightfm_customer_key(
                    settings.CHANNEL_ENCRYPTION_KEY,
                    business_id,
                    personalized_id,
                ) if personalized_id is not None else None
                model_score = score_lightfm_candidate(
                    live_reranker,
                    customer_key=customer_key,
                    product_id=product_id,
                    rfm_snapshot=rfm_snapshot,
                    personalization_allowed=personalized_id is not None,
                )
            else:
                model_score = score_live_candidate(
                    live_reranker,
                    item,
                    rank=rank,
                    rfm_snapshot=rfm_snapshot,
                    personalization_allowed=personalized_id is not None,
                )
            if model_score is None or not math.isfinite(float(model_score)):
                continue
            model_scores[product_id] = float(model_score)
        if len(model_scores) >= 2:
            query_intent, retrieval_weight = live_reranker_blend_profile(payload.query)
            blended_scores = blend_candidate_scores(
                baseline_scores,
                model_scores,
                baseline_weight=retrieval_weight,
            )
            for item in rerank_pool:
                product_id = int(item["product_id"])
                baseline_score = baseline_scores[product_id]
                model_score = model_scores.get(product_id)
                blended_score = blended_scores[product_id]
                item["feature_snapshot"]["live_reranker_baseline_score"] = round(baseline_score, 8)
                item["feature_snapshot"]["live_reranker_baseline_rank"] = baseline_ranks[product_id]
                item["feature_snapshot"]["live_reranker_blend_version"] = LIVE_RERANKER_BLEND_VERSION
                item["feature_snapshot"]["live_reranker_blended_score"] = round(blended_score, 8)
                if model_score is not None:
                    item["model_score"] = round(model_score, 8)
                    item["feature_snapshot"]["live_reranker_score"] = round(model_score, 8)
                    item["reason"] = f"{reranker_algorithm}_blend"
                item["score"] = round(blended_score, 8)
            rerank_pool.sort(key=lambda item: (
                -item["score"],
                baseline_ranks[int(item["product_id"])],
                int(item["product_id"]),
            ))
            scored_items = rerank_pool + scored_items[50:]
            request_context["behavioral_reranker"] = {
                "algorithm": reranker_algorithm,
                "blend_version": LIVE_RERANKER_BLEND_VERSION,
                "training_run_id": live_reranker_run_id,
                "applied": True,
                "query_intent": query_intent,
                "retrieval_weight": retrieval_weight,
                "model_weight": round(1.0 - retrieval_weight, 2),
                "candidate_pool_size": len(rerank_pool),
                "scored_candidate_count": len(model_scores),
                "score_normalization": "min_max_per_candidate_pool",
            }
            request_context["blend_version"] = LIVE_RERANKER_BLEND_VERSION
        else:
            request_context["behavioral_reranker"] = {
                "algorithm": reranker_algorithm,
                "training_run_id": live_reranker_run_id,
                "applied": False,
                "reason": "fewer_than_two_valid_candidate_scores",
                "candidate_pool_size": len(rerank_pool),
                "scored_candidate_count": len(model_scores),
            }
    served_items = scored_items[:payload.limit]
    for item in scored_items:
        item["feature_snapshot"]["staff_interest_score"] = round(
            float(manual_interest_scores.get(int(item["product_id"]), 0.0)), 6,
        )
        item["feature_snapshot"]["model_score"] = item.get("model_score")
        item["feature_snapshot"]["final_score"] = float(item["score"])
    candidate_snapshot = [
        {
            "product_id": int(item["product_id"]),
            "rank": rank,
            "score": float(item["score"]),
            "quality_validation": item.get("quality_validation"),
            "feature_snapshot": item.get("feature_snapshot", {}),
        }
        for rank, item in enumerate(scored_items[:50], start=1)
    ]
    request_context["candidate_snapshot"] = candidate_snapshot
    for position, item in enumerate(served_items, start=1):
        item["position"] = position
        item["selection_probability"] = None
    used_personalization_signals = sorted({
        signal
        for item in served_items
        for signal in item.get("personalization_signals", [])
    })
    request_id = str(uuid4())
    for item in served_items:
        if item.get("product_url"):
            click_url = _recommendation_click_url(
                business_id=business_id,
                request_id=request_id,
                product_id=int(item["product_id"]),
            )
            if click_url:
                item["click_url"] = click_url
    model_versions = [MODEL_VERSION]
    reranker_trace = request_context.get("behavioral_reranker")
    if isinstance(reranker_trace, dict) and reranker_trace.get("applied"):
        model_versions.append(str(reranker_trace.get("algorithm") or LIVE_RERANKER_ALGORITHM))
    if data_rag_scores:
        model_versions.append("data_rag_demo_v1")
    if ncf_scores:
        model_versions.append("ncf_bpr_uci_demo")
    if linucb_scores:
        model_versions.append("linucb_uci_demo")
    row = RecommendationRequest(
        business_id=business_id,
        request_id=request_id,
        customer_id=personalized_id,
        experiment_id=selection_payload.experiment_id,
        bandit_decision_id=bandit_decision_id,
        strategy=strategy,
        model_version="+".join(model_versions),
        context={
            **request_context,
            "query": payload.query if personalized_id is not None else "",
            "rag_candidate_count": len(payload.rag_candidates),
            "eligible_candidate_count": len(scored_items),
            "artifact_segment": artifact_segment,
            "data_rag_status": data_rag_status,
            "linucb_matched_skus": len(linucb_scores),
            "ncf_matched_skus": len(ncf_scores),
            "customer_interaction_product_count": len(interaction_affinity),
            "staff_interest_product_count": len(manual_interest_scores),
            "historic_interest_token_count": len(historic_tokens),
            "personalization_applied": bool(used_personalization_signals),
            "personalization_signals": used_personalization_signals,
            "available_personalization_signals": sorted(available_personalization_signals),
            "ranking_elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "profile_as_of": cached_features.get("as_of"),
        },
        served_items=served_items,
    )
    if persist:
        db.add(row)
        db.flush()
        if record_impressions:
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
    verified_click: bool = False,
) -> RecommendationFeedback:
    if event_type != "click":
        raise RecommendationServiceError(
            "Chỉ ghi nhận click qua luồng feedback này; giỏ hàng, mua, bỏ qua và hoàn tiền phải do luồng máy chủ xác minh.",
            422,
        )
    if not verified_click:
        raise RecommendationServiceError(
            "Click chỉ được ghi nhận từ liên kết sản phẩm có chữ ký.",
            403,
        )
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
    row = apply_recommendation_outcome(
        db,
        request=request,
        product_id=product_id,
        event_type=event_type,
        idempotency_key=idempotency_key,
        metadata=metadata,
    )
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
    db.commit()
    db.refresh(row)
    return row


def _fit_shop_rfm_segmenter(profiles: list[dict]) -> tuple[list[int], dict]:
    """Fit a bounded, reproducible cluster model on one shop's eligible buyers."""
    if not profiles:
        return [], {"status": "no_eligible_buyers"}
    feature_names = ("recency_days", "frequency", "monetary")
    matrix = np.asarray([
        [math.log1p(max(0.0, float(profile[name]))) for name in feature_names]
        for profile in profiles
    ], dtype=np.float64)
    scaler = StandardScaler()
    normalized = scaler.fit_transform(matrix)
    cluster_count = min(4, len(profiles))
    model = MiniBatchKMeans(
        n_clusters=cluster_count,
        random_state=RFM_CLUSTER_RANDOM_STATE,
        n_init=10,
        max_iter=100,
        batch_size=min(1024, max(32, cluster_count * 8)),
        reassignment_ratio=0.01,
    )
    labels = model.fit_predict(normalized).astype(int).tolist()
    cluster_sizes = dict(Counter(str(label) for label in labels))
    if len(cluster_sizes) < 2 or len(cluster_sizes) >= len(profiles):
        return [-1] * len(profiles), {
            "status": "degenerate_clusters_fallback_to_rules",
            "requested_clusters": cluster_count,
            "cluster_sizes": cluster_sizes,
        }
    sample_size = min(5000, len(profiles))
    quality = round(float(silhouette_score(
        normalized,
        labels,
        sample_size=sample_size,
        random_state=RFM_CLUSTER_RANDOM_STATE,
    )), 6)
    return labels, {
        "status": "trained",
        "model_version": SEGMENT_MODEL_VERSION,
        "algorithm": SEGMENT_ALGORITHM,
        "preprocessing": "log1p + StandardScaler",
        "feature_names": list(feature_names),
        "random_state": RFM_CLUSTER_RANDOM_STATE,
        "training_customer_count": len(profiles),
        "requested_clusters": cluster_count,
        "cluster_count": len(cluster_sizes),
        "cluster_sizes": cluster_sizes,
        "silhouette_sample_size": sample_size,
        "silhouette_score": quality,
        "scaler_mean": [float(value) for value in scaler.mean_],
        "scaler_scale": [float(value) for value in scaler.scale_],
        "centers_scaled": [[float(value) for value in center] for center in model.cluster_centers_],
        "cluster_segment_labels": semantic_labels_for_centers(model.cluster_centers_.tolist()),
    }


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
        consent_rows = db.query(CustomerConsent.customer_id, CustomerConsent.status).filter(
            CustomerConsent.business_id == business_id,
            CustomerConsent.purpose == "personalization",
        ).order_by(CustomerConsent.id.asc()).all()
        latest_consent = {int(customer_id): status for customer_id, status in consent_rows}
        personalization_enabled = get_customer_fact_extraction_enabled(db, business_id)
        customers = [customer for customer in db.query(Customer).filter(
            Customer.business_id == business_id,
            Customer.status != "merged",
            Customer.fact_extraction_opt_out.is_(False),
        ).order_by(Customer.id.asc()).all()
            if personalization_enabled and latest_consent.get(customer.id) == "granted"]
        eligible_customer_ids = {customer.id for customer in customers}
        for profile in db.query(RecommendationCustomerProfile).filter(
            RecommendationCustomerProfile.business_id == business_id,
        ).all():
            if profile.customer_id not in eligible_customer_ids:
                db.delete(profile)
        now = _now()
        all_profiles = customer_rfm_profiles(db, business_id, as_of=now)
        profiles = [all_profiles[customer.id] for customer in customers if customer.id in all_profiles]
        if not profiles:
            run.algorithm = SEGMENT_ALGORITHM
            run.status, run.metrics, run.artifact, run.completed_at = "succeeded", {"customers": 0, "buyers": 0, "clusters": 0, "learning_ready": False, "minimum_cluster_customers": MIN_SEGMENT_CUSTOMERS}, {
                "model_version": RFM_RULES_VERSION,
                "segmenter_version": SEGMENT_MODEL_VERSION,
                "algorithm": SEGMENT_ALGORITHM,
                "reason": "no consented customers with personalization enabled",
            }, _now()
            db.commit()
            return run
        buyers = [profile for profile in profiles if profile["frequency"] > 0]
        learning_ready = len(buyers) >= MIN_SEGMENT_CUSTOMERS
        segmenter_report: dict = {"status": "insufficient_consenting_buyers"}
        labels: list[int] = []
        profile_model_version, algorithm = RFM_RULES_VERSION, "rfm_rules_insufficient_cluster_samples"
        if not learning_ready:
            labels = [-1] * len(buyers)
        else:
            labels, segmenter_report = _fit_shop_rfm_segmenter(buyers)
            if segmenter_report.get("status") == "trained":
                profile_model_version, algorithm = SEGMENT_MODEL_VERSION, SEGMENT_ALGORITHM
            else:
                labels = [-1] * len(buyers)
        by_customer = {p["customer_id"]: label for p, label in zip(buyers, labels)}
        labels = [by_customer.get(p["customer_id"], -1) for p in profiles]
        segment_by_customer = {
            int(profile["customer_id"]): (profile["segment_label"], profile["segment_name"], profile["rfm_scores"])
            for profile in profiles
        }
        group_counts: Counter[str] = Counter(name for _, name, _ in segment_by_customer.values())
        workspace = get_workspace_config(db, business_id)
        consented_peer_median = float(median(float(profile["monetary"]) for profile in buyers)) if len(buyers) >= 5 else None
        cluster_labels = segmenter_report.get("cluster_segment_labels") or {}
        prior_assigned = 0
        # Publish the final training-run identity in this transaction before
        # rebuilding profile signatures. The cache signature includes the
        # active run id/completion time, so setting these after the profile
        # loop would make every freshly trained profile look stale immediately.
        run.algorithm = algorithm
        run.status = "succeeded"
        run.completed_at = _now()
        run.artifact = {
            "model_version": profile_model_version,
            "segmenter_version": SEGMENT_MODEL_VERSION,
            "algorithm": algorithm,
            "segmenter": segmenter_report,
        }
        # Tenant runtime sessions disable autoflush; make the completed model
        # visible to the profile-signature query in the same transaction.
        db.flush()

        for profile, label in zip(profiles, labels):
            segment_key, segment_name, rfm_scores = segment_by_customer[int(profile["customer_id"])]
            row, _ = _cached_personalization_profile(
                db, business_id, int(profile["customer_id"]), rfm_profiles=all_profiles,
            )
            if label >= 0 and segmenter_report.get("status") == "trained":
                recommendation_label = str(cluster_labels.get(str(label), segment_key))
                recommendation_name = next((name for name, key in RFM_SEGMENT_KEYS.items() if key == recommendation_label), segment_name)
                model_assignment = {
                    "cluster_id": int(label),
                    "cluster_model_version": SEGMENT_MODEL_VERSION,
                    "cluster_model_source": "shop_trained",
                    "recommendation_segment_label": recommendation_label,
                    "recommendation_segment_name": recommendation_name,
                    "rfm_scores": rfm_scores,
                    "rfm_model_confidence": "shop_trained",
                }
            elif int(profile["frequency"]) > 0:
                try:
                    model_assignment = predict_industry_rfm_prior(
                        profile,
                        industry=workspace.get("recommendation_industry", "general_retail"),
                        peer_median_monetary=consented_peer_median,
                        consented_buyer_count=len(buyers),
                    )
                except IndustryRfmPriorUnavailable:
                    model_assignment = None
                model_assignment = model_assignment or {
                    "cluster_id": None,
                    "cluster_model_version": RFM_RULES_VERSION,
                    "cluster_model_source": "rules_artifact_unavailable",
                    "recommendation_segment_label": segment_key,
                    "recommendation_segment_name": segment_name,
                    "rfm_scores": rfm_scores,
                    "rfm_model_confidence": "fallback_rules",
                }
                prior_assigned += int(model_assignment.get("cluster_model_source") == "industry_prior")
            else:
                model_assignment = {
                    "cluster_id": None,
                    "cluster_model_version": RFM_RULES_VERSION,
                    "cluster_model_source": "no_purchase_rule",
                    "recommendation_segment_label": segment_key,
                    "recommendation_segment_name": segment_name,
                    "rfm_scores": rfm_scores,
                    "rfm_model_confidence": "no_purchase",
                }
            values = {
                "segment_label": segment_key,
                "features": {**row.features, **{key: profile[key] for key in ("recency_days", "frequency", "monetary", "total_items", "distinct_products", "avg_order_value")},
                             "has_completed_order": profile["frequency"] > 0,
                             "segment_name": segment_name,
                             "rfm_percentile_scores": rfm_scores,
                             **model_assignment,
                             "rfm_rules_version": RFM_RULES_VERSION,
                             "as_of": now.isoformat(), "basis": "all_completed_or_paid_delivered_net_of_refunds"},
                "model_version": RFM_RULES_VERSION,
                "trained_at": _now(),
            }
            if row is None:
                db.add(RecommendationCustomerProfile(business_id=business_id, customer_id=profile["customer_id"], **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        run.status = "succeeded"
        run.algorithm = algorithm
        run.metrics = {
            "customers": len(profiles),
            "personalization_consented_customers": len(profiles),
            "consented_buyers": len(buyers),
            "learning_ready": learning_ready and segmenter_report.get("status") == "trained",
            "minimum_cluster_customers": MIN_SEGMENT_CUSTOMERS,
            "industry_prior_assigned_customers": prior_assigned,
            "industry_prior_model_version": INDUSTRY_RFM_PRIOR_VERSION if prior_assigned else None,
            "recommendation_industry": workspace.get("recommendation_industry"),
            "clusters": len(set(labels) - {-1}),
            "orders_for_consented_customers": sum(profile["frequency"] for profile in profiles),
            "groups": dict(group_counts),
            "segmenter": {key: value for key, value in segmenter_report.items() if key not in {"scaler_mean", "scaler_scale", "centers_scaled"}},
        }
        run.artifact = {
            "model_version": profile_model_version,
            "segmenter_version": SEGMENT_MODEL_VERSION,
            "algorithm": algorithm,
            "segmenter": segmenter_report,
        }
        db.commit()
    except Exception as exc:
        db.rollback()
        run = db.get(RecommendationTrainingRun, training_run_id)
        if run is not None:
            run.status, run.error_message, run.completed_at = "failed", str(exc)[:500], _now()
            db.commit()
        raise
    return run
