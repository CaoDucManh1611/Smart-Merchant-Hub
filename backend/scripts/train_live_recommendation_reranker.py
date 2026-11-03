"""Train/evaluate the tenant's behavioral reranker from real recommendation logs.

Run from ``backend`` after setting the platform and tenant database URLs.
Use ``--all-shops`` to process every active, enabled tenant independently.
Pass ``--activate`` only to enable each artifact when its temporal holdout
gate shows no NDCG@3 regression.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from sqlalchemy import select
from sklearn.linear_model import LogisticRegression

from app.core.config import settings
from app.database.platform_session import PlatformSessionLocal
from app.database.tenant_session import tenant_session
from app.models.platform_control import TenantRegistry
from app.models.customer import Customer
from app.models.customer_collection import CustomerConsent
from app.models.recommendation import (
    CustomerProductInteraction,
    RecommendationFeedback,
    RecommendationRequest,
    RecommendationTrainingRun,
)
from app.models.recommendation_quality_gate import RecommendationShopModelState
from app.services.recommendation_learning import (
    FEATURE_NAMES,
    LIGHTFM_ALGORITHM,
    LIGHTFM_RFM_FEATURE_VERSION,
    LIGHTFM_RFM_MIN_CUSTOMER_COVERAGE,
    LIVE_RERANKER_ALGORITHM,
    LIVE_RERANKER_BLEND_VERSION,
    blend_candidate_scores,
    candidate_features,
    encode_lightfm_factors,
    fit_lightfm_rfm_boundaries,
    lightfm_customer_key,
    lightfm_rfm_snapshot_is_valid,
    lightfm_user_feature_names,
    live_reranker_blend_profile,
    normalize_reranker_scores,
    score_candidate,
    score_lightfm_candidate,
)
from app.services.customer_fact_extractor import get_customer_fact_extraction_enabled
from app.tenancy.schema import schema_name_for, validate_schema_name


POSITIVE_RELEVANCE = {"click": 1, "cart": 1, "checkout_intent": 1, "purchase": 3}
TRACKED_EVENTS = {"impression", "click", "cart", "checkout_intent", "purchase", "skip", "refund"}


def _group_temporal_at(group: dict[str, Any]) -> datetime:
    """Use when feedback was observed, falling back for legacy snapshots."""
    value = group.get("outcome_at") or group.get("created_at")
    if not isinstance(value, datetime):
        return datetime.min
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _is_offline_or_synthetic_request(request: RecommendationRequest) -> bool:
    context = request.context if isinstance(request.context, dict) else {}
    traffic_type = str(context.get("traffic_type") or "").casefold()
    if traffic_type in {"offline_eval", "offline_test", "synthetic"}:
        return True
    run_id = str(context.get("evaluation_run_id") or "").casefold()
    if run_id.startswith(("rag-snapshot:", "offline-eval:", "synthetic:")):
        return True
    # Older snapshot evaluations predate traffic_type and use 0 as a sentinel;
    # real persisted CRM conversation IDs are positive database IDs.
    if str(context.get("surface") or "").casefold() == "chatbot":
        try:
            if int(context.get("conversation_id")) <= 0:
                return True
        except (TypeError, ValueError):
            return True
    return False


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--business-id", type=int, help="Train one active shop.")
    target.add_argument("--all-shops", action="store_true", help="Train each active, enabled shop in isolation.")
    parser.add_argument("--lookback-days", type=int, default=180)
    parser.add_argument("--min-positive-events", type=int, default=30)
    parser.add_argument("--min-training-pairs", type=int, default=50)
    parser.add_argument("--min-training-requests", type=int, default=20)
    parser.add_argument("--min-holdout-requests", type=int, default=5)
    parser.add_argument("--min-consented-customers", type=int, default=10)
    parser.add_argument("--algorithm", choices=(LIVE_RERANKER_ALGORITHM, LIGHTFM_ALGORITHM), default=LIVE_RERANKER_ALGORITHM)
    parser.add_argument("--lightfm-components", type=int, default=32)
    parser.add_argument("--lightfm-epochs", type=int, default=30)
    parser.add_argument("--activate", action="store_true", help="Enable serving only when the temporal holdout gate passes.")
    return parser.parse_args()


def _shop_targets(business_id: int | None) -> list[tuple[int, str]]:
    query = select(TenantRegistry).where(
        TenantRegistry.state == "active",
        TenantRegistry.feature_enabled.is_(True),
    )
    if business_id is not None:
        query = query.where(TenantRegistry.business_id == business_id)
    query = query.order_by(TenantRegistry.business_id.asc())
    with PlatformSessionLocal() as platform_db:
        registries = platform_db.scalars(query).all()
        targets = []
        for registry in registries:
            resolved_business_id = int(registry.business_id)
            schema_name = validate_schema_name(str(registry.schema_name))
            if schema_name != schema_name_for(resolved_business_id):
                raise ValueError(f"tenant_schema_mismatch:{resolved_business_id}")
            targets.append((resolved_business_id, schema_name))
        return targets


def _candidate_map(request: RecommendationRequest) -> dict[int, dict[str, Any]]:
    context = request.context if isinstance(request.context, dict) else {}
    raw_candidates = context.get("candidate_snapshot")
    if not isinstance(raw_candidates, list):
        raw_candidates = request.served_items if isinstance(request.served_items, list) else []
    trace = context.get("behavioral_reranker")
    reranker_was_used = (
        any(algorithm in str(request.model_version or "") for algorithm in (LIVE_RERANKER_ALGORITHM, LIGHTFM_ALGORITHM))
        or isinstance(trace, dict) and trace.get("algorithm") in {LIVE_RERANKER_ALGORITHM, LIGHTFM_ALGORITHM}
    )
    if reranker_was_used:
        has_baseline_snapshot = (
            isinstance(trace, dict)
            and trace.get("blend_version") == LIVE_RERANKER_BLEND_VERSION
            and all(
                isinstance(raw, dict)
                and isinstance(raw.get("feature_snapshot"), dict)
                and raw["feature_snapshot"].get("live_reranker_baseline_score") is not None
                and raw["feature_snapshot"].get("live_reranker_baseline_rank") is not None
                for raw in raw_candidates
            )
        )
        if not has_baseline_snapshot:
            # Older pure-model records cannot provide a fair baseline comparison.
            return {}
    result: dict[int, dict[str, Any]] = {}
    for rank, raw in enumerate(raw_candidates, start=1):
        if not isinstance(raw, dict):
            continue
        try:
            product_id = int(raw.get("product_id"))
        except (TypeError, ValueError):
            continue
        feature_snapshot = raw.get("feature_snapshot") if isinstance(raw.get("feature_snapshot"), dict) else {}
        result[product_id] = {
            "product_id": product_id,
            "rank": int(
                feature_snapshot.get("live_reranker_baseline_rank")
                or raw.get("rank") or raw.get("position") or rank
            ),
            "position": int(raw.get("position") or raw.get("rank") or rank),
            "score": feature_snapshot.get("live_reranker_baseline_score", raw.get("score")),
            "feature_snapshot": feature_snapshot,
            "quality_validation": raw.get("quality_validation") if isinstance(raw.get("quality_validation"), dict) else None,
        }
    return result


def _load_groups(db, business_id: int, lookback_days: int) -> list[dict[str, Any]]:
    if not get_customer_fact_extraction_enabled(db, business_id):
        return []
    cutoff = datetime.utcnow() - timedelta(days=max(1, lookback_days))
    requests = db.query(RecommendationRequest).filter(
        RecommendationRequest.business_id == business_id,
        RecommendationRequest.created_at >= cutoff,
    ).order_by(RecommendationRequest.created_at.asc(), RecommendationRequest.id.asc()).all()
    requests = [request for request in requests if not _is_offline_or_synthetic_request(request)]
    customer_ids = {int(request.customer_id) for request in requests if request.customer_id is not None}
    if not customer_ids:
        return []
    eligible_customer_ids = {
        int(customer_id)
        for (customer_id,) in db.query(Customer.id).filter(
            Customer.business_id == business_id,
            Customer.id.in_(customer_ids),
            Customer.fact_extraction_opt_out.is_(False),
        ).all()
    }
    consent_started_at: dict[int, datetime] = {}
    for customer_id, status, granted_at, created_at in db.query(
        CustomerConsent.customer_id,
        CustomerConsent.status,
        CustomerConsent.granted_at,
        CustomerConsent.created_at,
    ).filter(
        CustomerConsent.business_id == business_id,
        CustomerConsent.customer_id.in_(eligible_customer_ids),
        CustomerConsent.purpose == "personalization",
    ).order_by(CustomerConsent.id.asc()).all():
        customer_key = int(customer_id)
        if str(status) == "granted":
            effective_at = granted_at or created_at
            if isinstance(effective_at, datetime):
                consent_started_at[customer_key] = _group_temporal_at({"created_at": effective_at})
            else:
                consent_started_at.pop(customer_key, None)
        else:
            consent_started_at.pop(customer_key, None)
    eligible_customer_ids = set(consent_started_at)
    requests = [
        request for request in requests
        if request.customer_id is not None
        and int(request.customer_id) in eligible_customer_ids
        and isinstance(request.created_at, datetime)
        and _group_temporal_at({"created_at": request.created_at}) >= consent_started_at[int(request.customer_id)]
    ]
    request_by_id = {request.id: request for request in requests}
    if not request_by_id:
        return []
    request_ids = list(request_by_id)

    events: dict[int, dict[int, dict[str, Any]]] = defaultdict(dict)

    def add_event(
        request_id: int | None,
        product_id: int | None,
        event_type: str,
        metadata: Any,
        occurred_at: datetime | None = None,
    ) -> None:
        request = request_by_id.get(request_id)
        if request is None or product_id is None or event_type not in TRACKED_EVENTS:
            return
        event_time = _group_temporal_at({"outcome_at": occurred_at, "created_at": request.created_at})
        if event_time < consent_started_at.get(int(request.customer_id), datetime.max):
            return
        entry = events[request_id].setdefault(
            product_id, {"impressed": False, "positions": [], "types": set(), "occurred_at": []},
        )
        entry["types"].add(event_type)
        entry["impressed"] = entry["impressed"] or event_type == "impression"
        entry["occurred_at"].append(event_time)
        if isinstance(metadata, dict):
            try:
                position = int(metadata.get("position"))
            except (TypeError, ValueError):
                position = 0
            if position > 0:
                entry["positions"].append(position)

    for row in db.query(CustomerProductInteraction).filter(
        CustomerProductInteraction.business_id == business_id,
        CustomerProductInteraction.recommendation_request_id.in_(request_ids),
        CustomerProductInteraction.event_type.in_(sorted(TRACKED_EVENTS)),
    ).yield_per(500):
        add_event(
            row.recommendation_request_id, row.product_id, row.event_type,
            row.event_metadata, row.occurred_at,
        )
    for row in db.query(RecommendationFeedback).filter(
        RecommendationFeedback.business_id == business_id,
        RecommendationFeedback.recommendation_request_id.in_(request_ids),
        RecommendationFeedback.event_type.in_(sorted(TRACKED_EVENTS)),
    ).yield_per(500):
        add_event(
            row.recommendation_request_id, row.product_id, row.event_type,
            row.event_metadata, row.occurred_at,
        )

    groups = []
    for request in requests:
        context = request.context if isinstance(request.context, dict) else {}
        candidates = _candidate_map(request)
        request_events = events.get(request.id, {})
        judged = {}
        for product_id, event in request_events.items():
            if product_id not in candidates:
                continue
            types = event["types"]
            relevance = 0
            for event_type, value in POSITIVE_RELEVANCE.items():
                if event_type in types:
                    relevance = max(relevance, value)
            if "refund" in types:
                relevance = 0
            judged[product_id] = {
                "relevance": relevance,
                "explicit_negative": relevance == 0 and bool(types & {"skip", "refund"}),
                "position": min(event["positions"]) if event["positions"] else candidates[product_id]["position"],
            }
        exposed = {
            product_id for product_id, event in request_events.items()
            if product_id in candidates and (event["impressed"] or judged.get(product_id, {}).get("relevance", 0) > 0 or judged.get(product_id, {}).get("explicit_negative"))
        }
        if len(exposed) < 2:
            continue
        rfm_snapshot = context.get("rfm_snapshot") if isinstance(context.get("rfm_snapshot"), dict) else None
        # These groups already passed the current, shop-scoped consent filter.
        personalization_allowed = True
        candidate_pool = [
            {
                **candidate,
                "features": candidate_features(
                    candidate,
                    rank=candidate["rank"],
                    rfm_snapshot=rfm_snapshot,
                    personalization_allowed=personalization_allowed,
                ),
            }
            for _product_id, candidate in sorted(candidates.items())
        ]
        pool_by_product_id = {item["product_id"]: item for item in candidate_pool}
        members = []
        for product_id in sorted(exposed):
            candidate = pool_by_product_id[product_id]
            relevance = judged.get(product_id, {}).get("relevance", 0)
            position = judged.get(product_id, {}).get("position", candidate["position"])
            members.append({
                **candidate,
                "logged_position": position,
                "relevance": relevance,
                "explicit_negative": judged.get(product_id, {}).get("explicit_negative", False),
            })
        selection = context.get("strategy_selection") if isinstance(context.get("strategy_selection"), dict) else {}
        try:
            propensity = float(selection.get("selection_probability", 1.0))
        except (TypeError, ValueError):
            propensity = 1.0
        propensity = min(1.0, max(0.05, propensity))
        groups.append({
            "business_id": int(business_id),
            "request_id": request.request_id,
            "customer_id": int(request.customer_id),
            "created_at": request.created_at,
            # Split on the latest observed impression/feedback for this slate,
            # not the request creation time. Delayed clicks or purchases must
            # not leak into a training window merely because the request was old.
            "outcome_at": max(
                (timestamp for event in request_events.values() for timestamp in event["occurred_at"]),
                default=_group_temporal_at({"created_at": request.created_at}),
            ),
            "query": str(context.get("query") or ""),
            "candidate_pool": candidate_pool,
            "members": members,
            "propensity": propensity,
            "rfm_snapshot": rfm_snapshot,
            "personalization_allowed": personalization_allowed,
            "positive_count": sum(member["relevance"] > 0 for member in members),
            "event_counts": {event: sum(event in values["types"] for values in request_events.values()) for event in TRACKED_EVENTS},
        })
    return groups


def _make_pairs(groups: list[dict[str, Any]], means: np.ndarray, scales: np.ndarray):
    features, labels, weights = [], [], []
    for group in groups:
        members = group["members"]
        positives = [member for member in members if member["relevance"] > 0]
        if not positives:
            continue
        inverse_propensity = min(5.0, 1.0 / group["propensity"])
        for positive in positives:
            for negative in members:
                if negative["product_id"] == positive["product_id"]:
                    continue
                if negative["relevance"] > 0:
                    if positive["relevance"] <= negative["relevance"]:
                        continue
                    negative_weight = 1.0
                else:
                    negative_weight = 1.0 if negative["explicit_negative"] else 0.15
                difference = (np.asarray(positive["features"]) - np.asarray(negative["features"])) / scales
                pair_weight = max(1.0, positive["relevance"]) * negative_weight * inverse_propensity
                features.extend((difference, -difference))
                labels.extend((1, 0))
                weights.extend((pair_weight, pair_weight))
    return np.asarray(features, dtype=float), np.asarray(labels, dtype=int), np.asarray(weights, dtype=float)


def _dcg(relevances: list[int], k: int) -> float:
    return sum((2**rel - 1) / math.log2(index + 2) for index, rel in enumerate(relevances[:k]) if rel > 0)


def _ranking_metrics(
    groups: list[dict[str, Any]],
    artifact: dict[str, Any] | None = None,
    *,
    ranking: str = "baseline",
) -> dict[str, Any]:
    ndcg, precision, metric_weights, evaluated = [], [], [], 0
    model_scored_requests = model_scored_candidates = candidate_count = 0
    for group in groups:
        members = group["members"]
        if not any(member["relevance"] > 0 for member in members):
            continue
        candidate_pool = group.get("candidate_pool") or members
        if ranking == "baseline" or artifact is None:
            ranked_pool = sorted(candidate_pool, key=lambda member: (member["rank"], member["product_id"]))
        else:
            baseline_scores = {}
            model_scores = {}
            for candidate in candidate_pool:
                product_id = int(candidate["product_id"])
                baseline_scores[product_id] = float(candidate.get("score") or 0.0)
                if artifact.get("algorithm") == LIGHTFM_ALGORITHM:
                    customer_key = lightfm_customer_key(
                        settings.CHANNEL_ENCRYPTION_KEY,
                        int(group.get("business_id") or 0),
                        int(group.get("customer_id") or 0),
                    )
                    model_scores[product_id] = score_lightfm_candidate(
                        artifact,
                        customer_key=customer_key,
                        product_id=product_id,
                        rfm_snapshot=group.get("rfm_snapshot"),
                        personalization_allowed=bool(group.get("personalization_allowed")),
                    )
                else:
                    model_scores[product_id] = score_candidate(
                        artifact,
                        candidate,
                        rank=candidate["rank"],
                        rfm_snapshot=group.get("rfm_snapshot"),
                        personalization_allowed=bool(group.get("personalization_allowed")),
                    )
            valid_model_scores = {
                product_id: float(score)
                for product_id, score in model_scores.items()
                if score is not None and math.isfinite(float(score))
            }
            model_scored_candidates += len(valid_model_scores)
            candidate_count += len(candidate_pool)
            if len(valid_model_scores) >= 2:
                model_scored_requests += 1
            if ranking == "blend":
                _query_intent, baseline_weight = live_reranker_blend_profile(group.get("query", ""))
                scores = blend_candidate_scores(
                    baseline_scores,
                    valid_model_scores,
                    baseline_weight=baseline_weight,
                )
            else:
                scores = normalize_reranker_scores(valid_model_scores)
            ranked_pool = sorted(
                candidate_pool,
                key=lambda member: (
                    -scores.get(int(member["product_id"]), 0.0),
                    int(member["rank"]),
                    int(member["product_id"]),
                ),
            )
        exposed_ids = {int(member["product_id"]) for member in members}
        relevance_by_id = {
            int(member["product_id"]): int(member["relevance"])
            for member in members
        }
        ranked = [member for member in ranked_pool if int(member["product_id"]) in exposed_ids]
        top = ranked[:3]
        relevances = [relevance_by_id[int(member["product_id"])] for member in top]
        ideal = sorted(relevance_by_id.values(), reverse=True)
        ndcg.append(_dcg(relevances, 3) / max(_dcg(ideal, 3), 1e-12))
        precision.append(sum(value > 0 for value in relevances) / max(1, len(top)))
        metric_weights.append(min(5.0, 1.0 / max(0.05, group["propensity"])))
        evaluated += 1
    weight_total = sum(metric_weights)
    return {
        "ndcg_at_3": round(
            sum(value * weight for value, weight in zip(ndcg, metric_weights)) / weight_total, 6,
        ) if ndcg else None,
        "precision_at_3": round(
            sum(value * weight for value, weight in zip(precision, metric_weights)) / weight_total, 6,
        ) if precision else None,
        "positive_holdout_requests": evaluated,
        "model_scored_positive_requests": model_scored_requests,
        "model_scored_candidates": model_scored_candidates,
        "candidate_count": candidate_count,
        "model_scored_request_rate": round(model_scored_requests / evaluated, 6) if evaluated else None,
        "model_scored_candidate_rate": round(model_scored_candidates / candidate_count, 6) if candidate_count else None,
    }


def _quality_violation_metrics(
    groups: list[dict[str, Any]],
    artifact: dict[str, Any] | None = None,
) -> dict[str, Any]:
    checked = violations = expected = missing = 0
    violations_by_check: dict[str, int] = defaultdict(int)
    for group in groups:
        pool = group.get("candidate_pool") or group.get("members", [])
        if artifact is None:
            ranked = sorted(pool, key=lambda item: (item["rank"], item["product_id"]))
        else:
            baseline_scores = {int(item["product_id"]): float(item.get("score") or 0.0) for item in pool}
            if artifact.get("algorithm") == LIGHTFM_ALGORITHM:
                customer_key = lightfm_customer_key(
                    settings.CHANNEL_ENCRYPTION_KEY,
                    int(group.get("business_id") or 0),
                    int(group.get("customer_id") or 0),
                )
                model_scores = {
                    int(item["product_id"]): score_lightfm_candidate(
                        artifact,
                        customer_key=customer_key,
                        product_id=int(item["product_id"]),
                        rfm_snapshot=group.get("rfm_snapshot"),
                        personalization_allowed=bool(group.get("personalization_allowed")),
                    )
                    for item in pool
                }
            else:
                model_scores = {
                    int(item["product_id"]): score_candidate(
                        artifact,
                        item,
                        rank=item["rank"],
                        rfm_snapshot=group.get("rfm_snapshot"),
                        personalization_allowed=bool(group.get("personalization_allowed")),
                    )
                    for item in pool
                }
            valid_scores = {
                key: float(value) for key, value in model_scores.items()
                if value is not None and math.isfinite(float(value))
            }
            _intent, baseline_weight = live_reranker_blend_profile(group.get("query", ""))
            blended = blend_candidate_scores(baseline_scores, valid_scores, baseline_weight=baseline_weight)
            ranked = sorted(pool, key=lambda item: (-blended.get(int(item["product_id"]), 0.0), item["rank"], item["product_id"]))
        for item in ranked[:3]:
            expected += 1
            validation = item.get("quality_validation")
            if not isinstance(validation, dict) or not isinstance(validation.get("compliant"), bool):
                missing += 1
                continue
            checked += 1
            if not validation["compliant"]:
                violations += 1
            for key, value in validation.items():
                if key.endswith("_match") or key in {"shop_match", "active", "available"}:
                    if value is False:
                        violations_by_check[key] += 1
    return {
        "rate": round(violations / checked, 6) if checked and checked == expected else None,
        "checked_items": checked,
        "expected_items": expected,
        "missing_validation_items": missing,
        "violations_by_check": dict(sorted(violations_by_check.items())),
    }


def _train_lightfm(groups: list[dict[str, Any]], args: argparse.Namespace) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    ordered = sorted(groups, key=_group_temporal_at)
    if len(ordered) < 2:
        return None, {"algorithm": LIGHTFM_ALGORITHM, "requests_with_exposures": len(ordered), "reason": "need at least two exposed requests for a temporal split"}
    split = min(len(ordered) - 1, max(1, int(len(ordered) * 0.8)))
    train_groups, holdout_groups = ordered[:split], ordered[split:]
    consented_customers = {int(group["customer_id"]) for group in ordered if group.get("customer_id") is not None}
    holdout_customers = {int(group["customer_id"]) for group in holdout_groups if group.get("customer_id") is not None}
    baseline_metrics = _ranking_metrics(holdout_groups, ranking="baseline")
    counts = {
        "algorithm": LIGHTFM_ALGORITHM,
        "split_method": "chronological_80_20",
        "blend_version": LIVE_RERANKER_BLEND_VERSION,
        "requests_with_exposures": len(ordered),
        "training_requests": len(train_groups),
        "holdout_requests": len(holdout_groups),
        "consented_customer_count": len(consented_customers),
        "holdout_consented_customer_count": len(holdout_customers),
        "holdout_positive_requests": baseline_metrics["positive_holdout_requests"],
        "baseline_ndcg_at_3": baseline_metrics["ndcg_at_3"],
        "baseline_precision_at_3": baseline_metrics["precision_at_3"],
        "training_start": _group_temporal_at(train_groups[0]).isoformat(),
        "training_end": _group_temporal_at(train_groups[-1]).isoformat(),
        "holdout_start": _group_temporal_at(holdout_groups[0]).isoformat(),
        "holdout_end": _group_temporal_at(holdout_groups[-1]).isoformat(),
        "temporal_split_basis": "latest_recommendation_event_occurred_at",
    }
    if len(consented_customers) < args.min_consented_customers:
        return None, {**counts, "reason": "insufficient explicitly consented customers for the configured shop threshold"}
    if len(holdout_customers) < 1 or baseline_metrics["positive_holdout_requests"] < args.min_holdout_requests:
        return None, {**counts, "reason": "insufficient consented positive holdout requests"}
    secret = str(settings.CHANNEL_ENCRYPTION_KEY or "")
    if len(secret.strip()) < 32:
        return None, {**counts, "reason": "CHANNEL_ENCRYPTION_KEY is required to pseudonymize LightFM user IDs"}
    try:
        from lightfm import LightFM
        from scipy.sparse import coo_matrix
    except ImportError:
        return None, {**counts, "reason": "optional LightFM dependency is not installed"}

    latest_train_rfm: dict[str, dict[str, Any]] = {}
    for group in train_groups:
        customer_id = group.get("customer_id")
        snapshot = group.get("rfm_snapshot")
        if customer_id is None or not group.get("personalization_allowed") or not lightfm_rfm_snapshot_is_valid(snapshot):
            continue
        user_key = lightfm_customer_key(secret, int(group["business_id"]), int(customer_id))
        if user_key:
            # train_groups are chronological; retain the latest valid snapshot
            # available before the holdout boundary.
            latest_train_rfm[user_key] = snapshot

    events: dict[tuple[str, int], float] = defaultdict(float)
    positive_events_by_user: dict[str, int] = defaultdict(int)
    positive_requests_by_user: dict[str, int] = defaultdict(int)
    for group in train_groups:
        customer_id = group.get("customer_id")
        if customer_id is None:
            continue
        user_key = lightfm_customer_key(secret, int(group["business_id"]), int(customer_id))
        if not user_key:
            continue
        request_positive = False
        for member in group["members"]:
            relevance = int(member.get("relevance") or 0)
            if relevance <= 0:
                continue
            product_id = int(member["product_id"])
            weight = min(5.0, max(1.0, float(relevance)) / max(0.2, float(group["propensity"])))
            events[(user_key, product_id)] = min(10.0, events[(user_key, product_id)] + weight)
            positive_events_by_user[user_key] += 1
            request_positive = True
        positive_requests_by_user[user_key] += int(request_positive)
    all_positive_user_keys = sorted({user_key for user_key, _ in events})
    user_keys = [user_key for user_key in all_positive_user_keys if user_key in latest_train_rfm]
    training_rfm_coverage = len(user_keys) / max(1, len(all_positive_user_keys))
    if training_rfm_coverage < LIGHTFM_RFM_MIN_CUSTOMER_COVERAGE:
        return None, {
            **counts,
            "training_user_count": len(all_positive_user_keys),
            "training_rfm_customer_count": len(user_keys),
            "training_rfm_customer_coverage": round(training_rfm_coverage, 6),
            "rfm_feature_version": LIGHTFM_RFM_FEATURE_VERSION,
            "reason": "insufficient consented training customers with a complete RFM snapshot",
        }
    eligible_users = set(user_keys)
    events = {pair: weight for pair, weight in events.items() if pair[0] in eligible_users}
    positive_events = sum(positive_events_by_user[key] for key in user_keys)
    positive_requests = sum(positive_requests_by_user[key] for key in user_keys)
    product_ids = sorted({product_id for _, product_id in events})
    if (
        positive_events < args.min_positive_events
        or positive_requests < args.min_training_requests
        or len(user_keys) < args.min_consented_customers
        or not product_ids
    ):
        return None, {
            **counts,
            "training_positive_events": positive_events,
            "training_positive_requests": positive_requests,
            "training_item_count": len(product_ids),
            "training_user_count": len(user_keys),
            "training_rfm_customer_count": len(user_keys),
            "training_rfm_customer_coverage": round(training_rfm_coverage, 6),
            "reason": "insufficient consented positive interactions for LightFM training",
        }

    user_indices = {key: index for index, key in enumerate(user_keys)}
    item_indices = {str(product_id): index for index, product_id in enumerate(product_ids)}
    rfm_boundaries = fit_lightfm_rfm_boundaries([latest_train_rfm[key] for key in user_keys])
    user_feature_names = sorted({
        name
        for user_key in user_keys
        for name in lightfm_user_feature_names(user_key, latest_train_rfm[user_key], rfm_boundaries)
    })
    user_feature_indices = {name: index for index, name in enumerate(user_feature_names)}
    feature_rows, feature_columns, feature_data = [], [], []
    for user_key, user_index in user_indices.items():
        names = lightfm_user_feature_names(user_key, latest_train_rfm[user_key], rfm_boundaries)
        if len(names) != 4:
            continue
        weight = 1.0 / len(names)
        for name in names:
            feature_rows.append(user_index)
            feature_columns.append(user_feature_indices[name])
            feature_data.append(weight)
    if len(feature_rows) != len(user_indices) * 4:
        return None, {
            **counts,
            "training_user_count": len(user_indices),
            "training_rfm_customer_count": len(user_indices),
            "training_rfm_customer_coverage": round(training_rfm_coverage, 6),
            "reason": "could not build complete shop-scoped RFM user features",
        }
    coordinates = [
        (user_indices[user_key], item_indices[str(product_id)], weight)
        for (user_key, product_id), weight in sorted(events.items())
    ]
    rows = np.asarray([row for row, _column, _weight in coordinates], dtype=np.int32)
    columns = np.asarray([column for _row, column, _weight in coordinates], dtype=np.int32)
    interaction_data = np.ones(len(coordinates), dtype=np.float32)
    sample_weights = np.asarray([weight for _row, _column, weight in coordinates], dtype=np.float32)
    shape = (len(user_indices), len(item_indices))
    interactions = coo_matrix((interaction_data, (rows, columns)), shape=shape, dtype=np.float32)
    weights = coo_matrix((sample_weights, (rows, columns)), shape=shape, dtype=np.float32)
    user_features = coo_matrix(
        (np.asarray(feature_data, dtype=np.float32), (feature_rows, feature_columns)),
        shape=(len(user_indices), len(user_feature_indices)),
        dtype=np.float32,
    )
    model = LightFM(
        no_components=max(8, min(64, int(args.lightfm_components))),
        loss="warp",
        random_state=41,
    )
    model.fit(
        interactions,
        user_features=user_features,
        sample_weight=weights,
        epochs=max(1, min(100, int(args.lightfm_epochs))),
        num_threads=1,
        verbose=False,
    )
    user_feature_factors, user_feature_factor_shape = encode_lightfm_factors(model.user_embeddings)
    item_factors, item_factor_shape = encode_lightfm_factors(model.item_embeddings)
    user_feature_biases, user_feature_bias_shape = encode_lightfm_factors(model.user_biases)
    item_biases, item_bias_shape = encode_lightfm_factors(model.item_biases)
    artifact = {
        "algorithm": LIGHTFM_ALGORITHM,
        "model_version": LIGHTFM_ALGORITHM,
        "blend_version": LIVE_RERANKER_BLEND_VERSION,
        "rfm_feature_version": LIGHTFM_RFM_FEATURE_VERSION,
        "rfm_boundaries": rfm_boundaries,
        "loss": "warp",
        "components": int(model.user_embeddings.shape[1]),
        "user_indices": user_indices,
        "user_feature_indices": user_feature_indices,
        "item_indices": item_indices,
        "user_feature_factors_f16_zlib": user_feature_factors,
        "user_feature_factor_shape": user_feature_factor_shape,
        "item_factors_f16_zlib": item_factors,
        "item_factor_shape": item_factor_shape,
        "user_feature_biases_f16_zlib": user_feature_biases,
        "user_feature_bias_shape": user_feature_bias_shape,
        "item_biases_f16_zlib": item_biases,
        "item_bias_shape": item_bias_shape,
        "trained_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    blended_metrics = _ranking_metrics(holdout_groups, artifact, ranking="blend")
    baseline_quality = _quality_violation_metrics(holdout_groups)
    blended_quality = _quality_violation_metrics(holdout_groups, artifact)
    metrics = {
        **counts,
        "training_positive_events": positive_events,
        "training_positive_requests": positive_requests,
        "training_item_count": len(product_ids),
        "training_user_count": len(user_keys),
        "training_rfm_customer_count": len(user_keys),
        "training_rfm_customer_coverage": round(training_rfm_coverage, 6),
        "holdout_rfm_customer_count": len({
            int(group["customer_id"])
            for group in holdout_groups
            if group.get("customer_id") is not None and lightfm_rfm_snapshot_is_valid(group.get("rfm_snapshot"))
        }),
        "rfm_feature_version": LIGHTFM_RFM_FEATURE_VERSION,
        "lightfm_user_feature_count": len(user_feature_indices),
        "lightfm_loss": "warp",
        "lightfm_components": artifact["components"],
        "lightfm_epochs": max(1, min(100, int(args.lightfm_epochs))),
        "blended_ndcg_at_3": blended_metrics["ndcg_at_3"],
        "blended_precision_at_3": blended_metrics["precision_at_3"],
        "model_scored_positive_requests": blended_metrics["model_scored_positive_requests"],
        "model_scored_positive_request_rate": blended_metrics["model_scored_request_rate"],
        "model_scored_candidate_rate": blended_metrics["model_scored_candidate_rate"],
        "blended_ndcg_delta_at_3": round(blended_metrics["ndcg_at_3"] - baseline_metrics["ndcg_at_3"], 6)
        if blended_metrics["ndcg_at_3"] is not None and baseline_metrics["ndcg_at_3"] is not None else None,
        "holdout_impressions": sum(group["event_counts"].get("impression", 0) for group in holdout_groups),
        "holdout_clicks": sum(group["event_counts"].get("click", 0) for group in holdout_groups),
        "holdout_carts": sum(group["event_counts"].get("cart", 0) for group in holdout_groups),
        "holdout_purchases": sum(group["event_counts"].get("purchase", 0) for group in holdout_groups),
        "holdout_skips": sum(group["event_counts"].get("skip", 0) for group in holdout_groups),
        "holdout_purchase_rate": round(
            sum(group["event_counts"].get("purchase", 0) for group in holdout_groups)
            / max(1, sum(group["event_counts"].get("impression", 0) for group in holdout_groups)), 6,
        ),
        "holdout_skip_rate": round(
            sum(group["event_counts"].get("skip", 0) for group in holdout_groups)
            / max(1, sum(group["event_counts"].get("impression", 0) for group in holdout_groups)), 6,
        ),
        "baseline_violation_rate": baseline_quality["rate"],
        "candidate_violation_rate": blended_quality["rate"],
        "baseline_violation_validation_coverage": round(baseline_quality["checked_items"] / max(1, baseline_quality["expected_items"]), 6),
        "candidate_violation_validation_coverage": round(blended_quality["checked_items"] / max(1, blended_quality["expected_items"]), 6),
        "baseline_violations_by_check": baseline_quality["violations_by_check"],
        "candidate_violations_by_check": blended_quality["violations_by_check"],
    }
    metrics["quality_gate_passed"] = bool(
        metrics["blended_ndcg_at_3"] is not None
        and metrics["baseline_ndcg_at_3"] is not None
        and metrics["blended_ndcg_at_3"] >= metrics["baseline_ndcg_at_3"]
        and metrics["holdout_positive_requests"] >= args.min_holdout_requests
        and metrics["consented_customer_count"] >= args.min_consented_customers
        and metrics["training_rfm_customer_coverage"] >= LIGHTFM_RFM_MIN_CUSTOMER_COVERAGE
        and (metrics["model_scored_positive_request_rate"] or 0.0) >= 0.80
        and metrics["baseline_violation_rate"] is not None
        and metrics["candidate_violation_rate"] is not None
        and metrics["baseline_violation_rate"] >= metrics["candidate_violation_rate"]
    )
    metrics["quality_gate_policy"] = {
        "minimum_ndcg_lift": 0.0,
        "minimum_holdout_requests": args.min_holdout_requests,
        "minimum_consented_customers": args.min_consented_customers,
        "minimum_training_rfm_customer_coverage": LIGHTFM_RFM_MIN_CUSTOMER_COVERAGE,
        "minimum_lightfm_scored_positive_request_rate": 0.80,
        "violation_rate_must_not_increase": True,
        "violation_validation_coverage_required": 1.0,
    }
    artifact["metrics"] = metrics
    artifact["serving_enabled"] = False
    return artifact, metrics


def _train(groups: list[dict[str, Any]], args: argparse.Namespace) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    # Keep direct callers that construct a minimal Namespace on the default
    # learned reranker; the CLI always supplies the selected algorithm.
    if getattr(args, "algorithm", LIVE_RERANKER_ALGORITHM) == LIGHTFM_ALGORITHM:
        return _train_lightfm(groups, args)
    groups.sort(key=_group_temporal_at)
    if len(groups) < 2:
        return None, {"requests_with_exposures": len(groups), "reason": "need at least two exposed requests for a temporal split"}
    split = min(len(groups) - 1, max(1, int(len(groups) * 0.8)))
    train_groups, holdout_groups = groups[:split], groups[split:]
    vectors = np.asarray([member["features"] for group in train_groups for member in group["members"]], dtype=float)
    means = vectors.mean(axis=0)
    scales = vectors.std(axis=0)
    scales[scales < 1e-8] = 1.0
    x, y, sample_weight = _make_pairs(train_groups, means, scales)
    positives = sum(group["positive_count"] for group in train_groups)
    train_request_count = sum(group["positive_count"] > 0 for group in train_groups)
    baseline_metrics = _ranking_metrics(holdout_groups, ranking="baseline")
    consented_customers = {int(group["customer_id"]) for group in groups if group.get("customer_id") is not None}
    holdout_customers = {int(group["customer_id"]) for group in holdout_groups if group.get("customer_id") is not None}
    split_timestamps = {
        "training_start": _group_temporal_at(train_groups[0]).isoformat(),
        "training_end": _group_temporal_at(train_groups[-1]).isoformat(),
        "holdout_start": _group_temporal_at(holdout_groups[0]).isoformat(),
        "holdout_end": _group_temporal_at(holdout_groups[-1]).isoformat(),
        "temporal_split_basis": "latest_recommendation_event_occurred_at",
    }
    counts = {
        **split_timestamps,
        "split_method": "chronological_80_20",
        "blend_version": LIVE_RERANKER_BLEND_VERSION,
        "requests_with_exposures": len(groups),
        "training_requests": train_request_count,
        "holdout_requests": len(holdout_groups),
        "consented_customer_count": len(consented_customers),
        "holdout_consented_customer_count": len(holdout_customers),
        "training_positive_product_events": positives,
        "training_pair_count": int(len(x) // 2),
        "holdout_positive_requests": baseline_metrics["positive_holdout_requests"],
        "baseline_ndcg_at_3": baseline_metrics["ndcg_at_3"],
        "baseline_precision_at_3": baseline_metrics["precision_at_3"],
    }
    if len(consented_customers) < args.min_consented_customers:
        return None, {**counts, "reason": "insufficient explicitly consented customers for the configured shop threshold"}
    if positives < args.min_positive_events or len(x) // 2 < args.min_training_pairs or train_request_count < args.min_training_requests:
        return None, {**counts, "reason": "insufficient behavioral labels for the configured training thresholds"}
    if baseline_metrics["positive_holdout_requests"] < args.min_holdout_requests:
        return None, {**counts, "reason": "insufficient positive holdout requests for a reliable temporal evaluation"}

    model = LogisticRegression(C=0.5, solver="lbfgs", max_iter=500)
    model.fit(x, y, sample_weight=sample_weight)
    artifact = {
        "algorithm": LIVE_RERANKER_ALGORITHM,
        "model_version": LIVE_RERANKER_ALGORITHM,
        "blend_version": LIVE_RERANKER_BLEND_VERSION,
        "feature_names": list(FEATURE_NAMES),
        "means": {name: float(value) for name, value in zip(FEATURE_NAMES, means)},
        "scales": {name: float(value) for name, value in zip(FEATURE_NAMES, scales)},
        "weights": {name: float(value) for name, value in zip(FEATURE_NAMES, model.coef_[0])},
        "intercept": float(model.intercept_[0]),
        "trained_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    blended_metrics = _ranking_metrics(holdout_groups, artifact, ranking="blend")
    baseline_quality = _quality_violation_metrics(holdout_groups)
    blended_quality = _quality_violation_metrics(holdout_groups, artifact)
    metrics = {
        **counts,
        "blended_ndcg_at_3": blended_metrics["ndcg_at_3"],
        "blended_precision_at_3": blended_metrics["precision_at_3"],
        "blended_ndcg_delta_at_3": round(
            blended_metrics["ndcg_at_3"] - baseline_metrics["ndcg_at_3"], 6,
        ) if blended_metrics["ndcg_at_3"] is not None and baseline_metrics["ndcg_at_3"] is not None else None,
        "blended_precision_delta_at_3": round(
            blended_metrics["precision_at_3"] - baseline_metrics["precision_at_3"], 6,
        ) if blended_metrics["precision_at_3"] is not None and baseline_metrics["precision_at_3"] is not None else None,
        "holdout_impressions": sum(group["event_counts"].get("impression", 0) for group in holdout_groups),
        "holdout_clicks": sum(group["event_counts"].get("click", 0) for group in holdout_groups),
        "holdout_carts": sum(group["event_counts"].get("cart", 0) for group in holdout_groups),
        "holdout_purchases": sum(group["event_counts"].get("purchase", 0) for group in holdout_groups),
        "holdout_skips": sum(group["event_counts"].get("skip", 0) for group in holdout_groups),
        "holdout_purchase_rate": round(
            sum(group["event_counts"].get("purchase", 0) for group in holdout_groups)
            / max(1, sum(group["event_counts"].get("impression", 0) for group in holdout_groups)), 6,
        ),
        "holdout_skip_rate": round(
            sum(group["event_counts"].get("skip", 0) for group in holdout_groups)
            / max(1, sum(group["event_counts"].get("impression", 0) for group in holdout_groups)), 6,
        ),
        "propensity_weighting": "inverse_strategy_selection_probability_capped_at_5",
        "baseline_violation_rate": baseline_quality["rate"],
        "candidate_violation_rate": blended_quality["rate"],
        "baseline_violation_validation_coverage": round(baseline_quality["checked_items"] / max(1, baseline_quality["expected_items"]), 6),
        "candidate_violation_validation_coverage": round(blended_quality["checked_items"] / max(1, blended_quality["expected_items"]), 6),
        "baseline_violations_by_check": baseline_quality["violations_by_check"],
        "candidate_violations_by_check": blended_quality["violations_by_check"],
    }
    metrics["quality_gate_passed"] = bool(
        metrics["blended_ndcg_at_3"] is not None
        and metrics["baseline_ndcg_at_3"] is not None
        and metrics["blended_ndcg_at_3"] >= metrics["baseline_ndcg_at_3"]
        and metrics["holdout_positive_requests"] >= args.min_holdout_requests
        and metrics["consented_customer_count"] >= args.min_consented_customers
        and metrics["baseline_violation_rate"] is not None
        and metrics["candidate_violation_rate"] is not None
        and metrics["baseline_violation_rate"] >= metrics["candidate_violation_rate"]
    )
    metrics["quality_gate_policy"] = {
        "minimum_ndcg_lift": 0.0,
        "minimum_holdout_requests": args.min_holdout_requests,
        "minimum_consented_customers": args.min_consented_customers,
        "violation_rate_must_not_increase": True,
        "violation_validation_coverage_required": 1.0,
    }
    artifact["metrics"] = metrics
    artifact["serving_enabled"] = False
    return artifact, metrics


def _save_shop_gate_state(
    db,
    business_id: int,
    metrics: dict[str, Any],
    *,
    enabled: bool,
    algorithm: str,
    model_version: str | None,
    training_run_id: int | None,
    last_training_run_id: int | None,
    gate_status: str,
    lookback_days: int,
) -> None:
    state = db.query(RecommendationShopModelState).filter(
        RecommendationShopModelState.business_id == business_id,
    ).one_or_none()
    if state is None:
        state = RecommendationShopModelState(business_id=business_id)
        db.add(state)
    state.algorithm = algorithm if enabled else "baseline"
    state.model_version = model_version if enabled else None
    state.gate_status = gate_status
    state.enabled = enabled
    state.sample_count = int(metrics.get("holdout_requests") or 0)
    state.consented_customer_count = int(metrics.get("consented_customer_count") or 0)
    state.baseline_ndcg = metrics.get("baseline_ndcg_at_3")
    state.candidate_ndcg = metrics.get("blended_ndcg_at_3")
    state.baseline_violation_rate = metrics.get("baseline_violation_rate")
    state.candidate_violation_rate = metrics.get("candidate_violation_rate")
    state.train_window = {
        "start": metrics.get("training_start"),
        "end": metrics.get("training_end"),
        "lookback_days": lookback_days,
        "split_method": metrics.get("split_method"),
    }
    state.holdout_window = {
        "start": metrics.get("holdout_start"),
        "end": metrics.get("holdout_end"),
    }
    state.metrics = {
        **metrics,
        "active_training_run_id": training_run_id if enabled else None,
        "last_training_run_id": last_training_run_id,
    }
    db.flush()


def _train_shop(business_id: int, schema_name: str, args: argparse.Namespace) -> dict[str, Any]:
    try:
        with tenant_session(schema_name) as db:
            groups = _load_groups(db, business_id, args.lookback_days)
            artifact, metrics = _train(groups, args)
            if artifact is None:
                attempt = RecommendationTrainingRun(
                    business_id=business_id,
                    algorithm=args.algorithm,
                    status="insufficient_data",
                    metrics=metrics,
                    artifact={},
                    started_at=datetime.utcnow(),
                    completed_at=datetime.utcnow(),
                )
                db.add(attempt)
                db.flush()
                existing = None
                if args.activate:
                    existing = db.query(RecommendationShopModelState).filter(
                        RecommendationShopModelState.business_id == business_id,
                    ).one_or_none()
                    if existing is not None and existing.enabled and existing.gate_status == "passed":
                        existing_metrics = existing.metrics if isinstance(existing.metrics, dict) else {}
                        existing.metrics = {
                            **existing_metrics,
                            "last_attempt": metrics,
                            "last_training_run_id": int(attempt.id),
                        }
                    else:
                        _save_shop_gate_state(
                            db, business_id, metrics, enabled=False, algorithm=args.algorithm,
                            model_version=None, training_run_id=None,
                            last_training_run_id=int(attempt.id), gate_status="insufficient_data",
                            lookback_days=args.lookback_days,
                        )
                db.commit()
                return {
                    "business_id": business_id,
                    "status": "insufficient_data",
                    "training_run_id": int(attempt.id),
                    "previous_model_preserved": bool(args.activate and existing is not None and existing.enabled),
                    "metrics": metrics,
                }
            activated = bool(args.activate and metrics.get("quality_gate_passed"))
            artifact["serving_enabled"] = activated
            artifact_algorithm = str(artifact.get("algorithm") or args.algorithm)
            run = RecommendationTrainingRun(
                business_id=business_id,
                algorithm=artifact_algorithm,
                status="succeeded",
                metrics=metrics,
                artifact=artifact,
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
            )
            db.add(run)
            db.flush()
            artifact["model_version"] = f"{artifact_algorithm}:{run.id}:{artifact['trained_at'][:19]}"
            run.artifact = artifact
            if args.activate:
                _save_shop_gate_state(
                    db,
                    business_id,
                    metrics,
                    enabled=activated,
                    algorithm=artifact_algorithm,
                    model_version=artifact["model_version"] if activated else None,
                    training_run_id=int(run.id) if activated else None,
                    last_training_run_id=int(run.id),
                    gate_status="passed" if activated else "rejected",
                    lookback_days=args.lookback_days,
                )
            db.commit()
            return {
                "business_id": business_id,
                "status": "activated" if activated else "trained_not_activated",
                "training_run_id": int(run.id),
                "serving_enabled": activated,
                "activation_requested": bool(args.activate),
                "quality_gate_passed": metrics.get("quality_gate_passed"),
                "metrics": metrics,
            }
    except Exception as error:
        return {"business_id": business_id, "status": "failed", "error_type": type(error).__name__}


def main() -> int:
    args = _parse_args()
    targets = _shop_targets(None if args.all_shops else args.business_id)
    if not targets:
        print(json.dumps({"status": "no_active_enabled_shops", "results": []}, ensure_ascii=False, indent=2))
        return 2 if args.business_id is not None else 0
    results = [_train_shop(business_id, schema_name, args) for business_id, schema_name in targets]
    failed = any(result["status"] == "failed" for result in results)
    print(json.dumps({
        "status": "failed" if failed else "completed",
        "shop_count": len(results),
        "activation_requested": bool(args.activate),
        "results": results,
    }, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
