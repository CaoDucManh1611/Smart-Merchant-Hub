"""Recommendation pipeline: source -> filter -> scorer -> selector -> feedback."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import random
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
from urllib.parse import urlsplit

from sqlalchemy import and_, func, or_, select
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
from app.models.sales import Order, OrderItem, Product
from app.schemas.recommendation import RecommendationRequestCreate
from app.services.recommendation_artifacts import RecommendationArtifactError, registry as artifact_registry
from app.services.recommendation_artifacts import stated_budget
from app.rag.topics import fold_topic_text
from app.services.customer_fact_extractor import get_customer_fact_extraction_enabled
from app.services.recommendation_interaction_service import (
    apply_recommendation_outcome,
    record_interaction,
    record_recommendation_impressions,
)
from app.services.order_metrics import completed_order_conditions, net_order_value
from app.services.rfm_segments import RFM_RULES_VERSION, RFM_SEGMENT_KEYS, rfm_group, rfm_score


REVENUE_ORDER_STATUSES = ("delivered", "completed")
MODEL_VERSION = "item_affinity_rfm_v3"
SEGMENT_MODEL_VERSION = "rfm_kmeans_v2"
STRATEGIES = {"balanced", "personalized", "popular", "rag"}
MIN_BANDIT_TRAINING_EVENTS = 20
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
        minimum_events = max(1, min(10000, int(
            (policy.config or {}).get("min_training_events", MIN_BANDIT_TRAINING_EVENTS)
        )))
    except (AttributeError, TypeError, ValueError):
        minimum_events = MIN_BANDIT_TRAINING_EVENTS
    if observed_outcomes < minimum_events:
        # Keep the experiment on its first declared variant until enough
        # terminal outcomes exist; impressions/clicks alone are not rewards.
        strategy, reason = variants[0], "warmup_default"
    else:
        explore = random.random() < float(policy.epsilon)
        if explore or not any(stat and stat.pulls for stat in stats.values()):
            strategy, reason = random.choice(variants), "exploration"
        else:
            strategy = max(variants, key=lambda arm: (
                float(((stats[arm].reward_sum or 0) / max(1, stats[arm].pulls)) if stats[arm] else 0),
                arm,
            ))
            reason = "exploitation"
    decision = BanditDecision(
        business_id=business_id,
        experiment_id=experiment.id,
        subject_key=subject_key,
        arm=strategy,
        context=context,
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


def serve_recommendations(db: Session, *, business_id: int, payload: RecommendationRequestCreate) -> RecommendationRequest:
    customer = _customer_or_raise(db, business_id, payload.customer_id)
    personalized_id = customer.id if customer and _personalization_allowed(db, business_id, customer.id) else None
    selection_payload = payload
    if customer is not None and personalized_id is None:
        selection_payload = payload.model_copy(update={"context": {}, "experiment_id": None})
    subject_key = f"customer:{personalized_id}" if personalized_id else "anonymous"
    profile = None
    if personalized_id is not None:
        profile = db.query(RecommendationCustomerProfile).filter(
            RecommendationCustomerProfile.business_id == business_id,
            RecommendationCustomerProfile.customer_id == personalized_id,
        ).first()
    rfm_segment = profile.segment_label if profile else "unclassified"
    learning_context = {
        **selection_payload.context,
        "rfm_segment": rfm_segment,
        "rfm_rules_version": RFM_RULES_VERSION,
        "source_channel": customer.channel,
    } if personalized_id is not None and customer is not None else {}
    strategy, bandit_decision_id = _select_strategy(
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
    request_context = {**learning_context, "ranking_weights": ranking_weights}
    recent, historical = _recent_and_historical_products(db, business_id, personalized_id)
    candidates = db.query(Product).filter(
        Product.business_id == business_id,
        Product.status == "active",
        Product.stock_quantity > Product.reserved_quantity,
    ).order_by(Product.id.asc()).all()
    candidates = [product for product in candidates if product.id not in recent]
    candidates = _filter_query_candidates(candidates, payload.query)
    data_rag_scores, data_rag_status = {}, "disabled"
    customer_features = _customer_recommendation_features(db, business_id, personalized_id)
    artifact_segment, linucb_scores, ncf_scores = _demo_artifact_scores(customer if personalized_id else None, candidates, customer_features)
    popularity = _popular_counts(db, business_id)
    affinity = _co_purchase_counts(db, business_id, historical)
    interaction_affinity = _interaction_scores(db, business_id=business_id, customer_id=personalized_id) if personalized_id else Counter()
    purchase_facets = _customer_purchase_facets(db, business_id, personalized_id)
    interaction_popularity = _interaction_scores(db, business_id=business_id)
    historic_tokens = _historic_query_tokens(db, business_id, personalized_id)
    preferred_color, color_signal = _preferred_color(db, business_id, personalized_id)
    stated_preferences = _stated_preference_values(db, business_id, personalized_id)
    available_personalization_signals = set()
    if personalized_id is not None:
        if historical:
            available_personalization_signals.add("order_history")
        if any(value != 0 for value in interaction_affinity.values()):
            available_personalization_signals.add("product_interest")
        if stated_preferences or color_signal == "explicit_color_preference":
            available_personalization_signals.add("stated_preferences")
        if historic_tokens:
            available_personalization_signals.add("past_questions")
        if profile and profile.segment_label and profile.segment_label != "unclassified":
            available_personalization_signals.add("rfm_segment")
    rag_scores = {candidate.product_id: candidate.relevance for candidate in payload.rag_candidates}
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
        historic_query_score = _historic_interest_overlap(historic_tokens, product)
        lexical_score = max(current_query_score, 0.35 * historic_query_score)
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
        if personalized_id is not None and rfm_segment and rfm_segment != "unclassified":
            item_signals.add("rfm_segment")
        scored_items.append({
            "product_id": product.id,
            "sku": product.sku,
            "name": product.name,
            "price": float(product.price or 0),
            "available": max(int(product.stock_quantity or 0) - int(product.reserved_quantity or 0), 0),
            "product_url": safe_http_url(product.product_url),
            "score": round(score, 6),
            "model_score": round(data_rag_scores[product.id], 6) if product.id in data_rag_scores else None,
            "reason": reason,
            "personalization_signals": sorted(item_signals),
            "purchase_facets": matched_purchase_facets,
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
    served_items = scored_items[:payload.limit]
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
            "historic_interest_token_count": len(historic_tokens),
            "personalization_applied": bool(used_personalization_signals),
            "personalization_signals": used_personalization_signals,
            "available_personalization_signals": sorted(available_personalization_signals),
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
        orders = db.query(Order).filter(
            Order.business_id == business_id,
            *_completed_order_conditions(),
        ).all()
        by_customer: defaultdict[int, list[Order]] = defaultdict(list)
        for order in orders:
            by_customer[int(order.customer_id)].append(order)
        now = _now()
        item_rows = db.query(Order.customer_id, OrderItem.product_id, OrderItem.quantity).join(
            Order, Order.id == OrderItem.order_id
        ).filter(
            Order.business_id == business_id,
            *_completed_order_conditions(),
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
            monetary = float(sum((_net_order_value(order) for order in customer_orders), Decimal("0")))
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
            run.status, run.metrics, run.artifact, run.completed_at = "succeeded", {"customers": 0, "clusters": 0}, {
                "model_version": SEGMENT_MODEL_VERSION, "segmenter_version": RFM_RULES_VERSION,
            }, _now()
            db.commit()
            return run
        buyers = [profile for profile in profiles if profile["frequency"] > 0]
        labels = []
        profile_model_version, algorithm = SEGMENT_MODEL_VERSION, "deterministic_rfm_kmeans"
        try:
            imported = [artifact_registry.data_rag_segment(business_id, profile) for profile in buyers]
            if imported and all(label is not None for label in imported):
                labels = [int(label) for label in imported]
                profile_model_version, algorithm = "data_rag_rfm_demo_v1", "imported_data_rag_kmeans"
            else:
                imported = [artifact_registry.demo_segmentation_label(profile) for profile in buyers]
                if imported and all(label is not None for label in imported):
                    labels = [int(label) for label in imported]
                    profile_model_version, algorithm = "uci_kmeans_demo_v1", "imported_uci_kmeans"
        except (RecommendationArtifactError, KeyError, TypeError, ValueError):
            labels = []
        if buyers and not labels:
            raw = [[math.log1p(max(0.0, float(profile[key]))) for key in ("recency_days", "frequency", "monetary")] for profile in buyers]
            means = [sum(v[i] for v in raw) / len(raw) for i in range(3)]
            deviations = [math.sqrt(sum((v[i] - means[i]) ** 2 for v in raw) / len(raw)) or 1.0 for i in range(3)]
            normalized = [[(v[i] - means[i]) / deviations[i] for i in range(3)] for v in raw]
            labels = _kmeans(normalized, min(4, len(buyers)))
        by_customer = {p["customer_id"]: label for p, label in zip(buyers, labels)}
        labels = [by_customer.get(p["customer_id"], -1) for p in profiles]
        buyers = [profile for profile in profiles if profile["frequency"] > 0]
        recencies = [float(profile["recency_days"]) for profile in buyers]
        frequencies = [float(profile["frequency"]) for profile in buyers]
        monetary_values = [float(profile["monetary"]) for profile in buyers]
        segment_by_customer: dict[int, tuple[str, str, dict[str, int] | None]] = {}
        for profile in profiles:
            customer_id = int(profile["customer_id"])
            if not profile["frequency"]:
                segment_by_customer[customer_id] = ("no_purchase", "RFM · Chưa mua", None)
                continue
            recency_score = rfm_score(float(profile["recency_days"]), recencies, lower_is_better=True)
            frequency_score = rfm_score(float(profile["frequency"]), frequencies)
            monetary_score = rfm_score(float(profile["monetary"]), monetary_values)
            first_purchase_recent = profile["frequency"] == 1 and profile["recency_days"] <= 30
            name = rfm_group(
                recency_score,
                frequency_score,
                monetary_score,
                first_purchase_recent=first_purchase_recent,
            )
            segment_by_customer[customer_id] = (
                RFM_SEGMENT_KEYS[name],
                name,
                {"recency": recency_score, "frequency": frequency_score, "monetary": monetary_score},
            )
        group_counts: Counter[str] = Counter(name for _, name, _ in segment_by_customer.values())

        for profile, label in zip(profiles, labels):
            segment_key, segment_name, rfm_scores = segment_by_customer[int(profile["customer_id"])]
            row = db.query(RecommendationCustomerProfile).filter(
                RecommendationCustomerProfile.business_id == business_id,
                RecommendationCustomerProfile.customer_id == profile["customer_id"],
            ).first()
            values = {
                "segment_label": segment_key,
                "features": {**{key: profile[key] for key in ("recency_days", "frequency", "monetary", "total_items", "distinct_products", "avg_order_value")},
                             "has_completed_order": profile["frequency"] > 0, "cluster_id": label if label >= 0 else None,
                             "segment_name": segment_name,
                             "rfm_scores": rfm_scores, "rfm_rules_version": RFM_RULES_VERSION,
                             "cluster_model_version": profile_model_version,
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
        run.metrics = {
            "customers": len(profiles),
            "clusters": len(set(labels) - {-1}),
            "orders": len(orders),
            "groups": dict(group_counts),
        }
        run.artifact = {
            "model_version": profile_model_version,
            "segmenter_version": RFM_RULES_VERSION,
            "algorithm": algorithm,
        }
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
