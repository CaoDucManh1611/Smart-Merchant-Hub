"""Feature contract shared by online recommendation serving and offline training."""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
import zlib
from functools import lru_cache
from typing import Any

import numpy as np

from app.rag.topics import fold_topic_text


FEATURE_NAMES = (
    "baseline_score",
    "baseline_rank",
    "catalog_match_score",
    "query_overlap_score",
    "rag_relevance",
    "rag_bm25_score",
    "rag_vector_score",
    "rag_rrf_score",
    "rag_ppr_score",
    "rag_bm25_rank",
    "rag_vector_rank",
    "rag_rrf_rank",
    "rag_ppr_rank",
    "rag_retrieval_rank",
    "affinity_score",
    "co_purchase_score",
    "interaction_score",
    "purchase_facet_score",
    "historic_query_overlap_score",
    "stated_preference_score",
    "color_match",
    "ncf_score",
    "linucb_score",
    "staff_interest_score",
    "rfm_recency_log",
    "rfm_frequency_log",
    "rfm_monetary_log",
    "rag_relevance_x_rfm_recency",
    "rag_relevance_x_rfm_frequency",
    "rag_relevance_x_rfm_monetary",
    "affinity_score_x_rfm_frequency",
    "co_purchase_score_x_rfm_frequency",
    "interaction_score_x_rfm_frequency",
    "purchase_facet_score_x_rfm_frequency",
)
LIVE_RERANKER_ALGORITHM = "live_feedback_pairwise_reranker_v1"
LIGHTFM_ALGORITHM = "lightfm_warp_rfm_v2"
LEGACY_LIGHTFM_ALGORITHMS = ("lightfm_warp_v1",)
LIGHTFM_RFM_FEATURE_VERSION = "consented_shop_rfm_quintiles_v1"
LIGHTFM_RFM_MIN_CUSTOMER_COVERAGE = 0.80
LIVE_RERANKER_BLEND_VERSION = "normalized_baseline_blend_v1"


def lightfm_customer_key(secret: str, business_id: int, customer_id: int) -> str | None:
    """Return a shop-scoped pseudonymous ID; raw customer IDs never enter artifacts."""
    key = str(secret or "").encode("utf-8")
    if len(key) < 32:
        return None
    payload = f"smh-lightfm-v1:{int(business_id)}:{int(customer_id)}".encode("utf-8")
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def score_lightfm_candidate(
    artifact: dict[str, Any],
    *,
    customer_key: str | None,
    product_id: int,
    rfm_snapshot: dict[str, Any] | None = None,
    personalization_allowed: bool = False,
) -> float | None:
    """Score a consented customer/product pair using identity and current RFM features."""
    if (
        not customer_key
        or not personalization_allowed
        or artifact.get("algorithm") != LIGHTFM_ALGORITHM
        or artifact.get("rfm_feature_version") != LIGHTFM_RFM_FEATURE_VERSION
    ):
        return None
    users = artifact.get("user_indices")
    items = artifact.get("item_indices")
    feature_indices = artifact.get("user_feature_indices")
    if not all(isinstance(value, dict) for value in (users, items, feature_indices)):
        return None
    if customer_key not in users:
        return None
    item_index = items.get(str(int(product_id)))
    identity_index = feature_indices.get(f"identity:{customer_key}")
    if item_index is None or identity_index is None:
        return None
    rfm_features = lightfm_rfm_feature_names(rfm_snapshot, artifact.get("rfm_boundaries"))
    if len(rfm_features) != len(_LIGHTFM_RFM_FIELDS):
        return None
    try:
        selected_feature_indices = [int(identity_index)]
        for feature_name in rfm_features:
            feature_index = feature_indices.get(feature_name)
            if feature_index is not None:
                selected_feature_indices.append(int(feature_index))
        if len(selected_feature_indices) != len(_LIGHTFM_RFM_FIELDS) + 1:
            return None
        user_shape = tuple(int(value) for value in artifact["user_feature_factor_shape"])
        item_shape = tuple(int(value) for value in artifact["item_factor_shape"])
        user_bias_shape = tuple(int(value) for value in artifact["user_feature_bias_shape"])
        item_bias_shape = tuple(int(value) for value in artifact["item_bias_shape"])
        user_vectors = _decode_factors(artifact["user_feature_factors_f16_zlib"], user_shape)
        item_vectors = _decode_factors(artifact["item_factors_f16_zlib"], item_shape)
        user_biases = _decode_factors(artifact["user_feature_biases_f16_zlib"], user_bias_shape)
        item_biases = _decode_factors(artifact["item_biases_f16_zlib"], item_bias_shape)
        feature_weight = 1.0 / len(selected_feature_indices)
        user_vector = np.sum(user_vectors[selected_feature_indices].astype(np.float32), axis=0) * feature_weight
        item_vector = item_vectors[int(item_index)]
        if len(user_vector) != len(item_vector):
            return None
        score = sum(float(left) * float(right) for left, right in zip(user_vector, item_vector))
        score += float(np.sum(user_biases[selected_feature_indices].astype(np.float32)) * feature_weight)
        score += float(item_biases[int(item_index)])
    except (KeyError, IndexError, TypeError, ValueError, OverflowError, zlib.error):
        return None
    return score if math.isfinite(score) else None


_LIGHTFM_RFM_FIELDS = ("recency_days", "frequency", "monetary")


def _valid_lightfm_rfm_snapshot(snapshot: Any) -> dict[str, float] | None:
    if not isinstance(snapshot, dict):
        return None
    values: dict[str, float] = {}
    for field in _LIGHTFM_RFM_FIELDS:
        try:
            value = float(snapshot[field])
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(value) or value < 0:
            return None
        values[field] = value
    return values


def lightfm_rfm_snapshot_is_valid(snapshot: Any) -> bool:
    return _valid_lightfm_rfm_snapshot(snapshot) is not None


def fit_lightfm_rfm_boundaries(snapshots: list[dict[str, Any]]) -> dict[str, list[float]]:
    """Fit shop-local RFM quintile cut points from training-period snapshots only."""
    values_by_field = {field: [] for field in _LIGHTFM_RFM_FIELDS}
    for snapshot in snapshots:
        values = _valid_lightfm_rfm_snapshot(snapshot)
        if values is None:
            continue
        for field, value in values.items():
            values_by_field[field].append(value)
    return {
        field: [float(value) for value in np.quantile(values, [0.2, 0.4, 0.6, 0.8])]
        for field, values in values_by_field.items()
        if values
    }


def lightfm_rfm_feature_names(
    snapshot: dict[str, Any] | None,
    boundaries: Any,
) -> list[str]:
    values = _valid_lightfm_rfm_snapshot(snapshot)
    if values is None or not isinstance(boundaries, dict):
        return []
    features = []
    for field in _LIGHTFM_RFM_FIELDS:
        try:
            cuts = [float(value) for value in boundaries[field]]
        except (KeyError, TypeError, ValueError, OverflowError):
            return []
        if len(cuts) != 4 or not all(math.isfinite(value) for value in cuts):
            return []
        bucket = int(np.searchsorted(cuts, values[field], side="right")) + 1
        if field == "recency_days":
            bucket = 6 - bucket
        features.append(f"rfm:{field}:{bucket}")
    return features


def lightfm_user_feature_names(
    customer_key: str,
    snapshot: dict[str, Any] | None,
    boundaries: Any,
) -> list[str]:
    return [f"identity:{customer_key}", *lightfm_rfm_feature_names(snapshot, boundaries)]


@lru_cache(maxsize=8)
def _decode_factors(encoded: str, shape: tuple[int, ...]) -> np.ndarray:
    raw = zlib.decompress(base64.b64decode(encoded.encode("ascii")))
    return np.frombuffer(raw, dtype=np.float16).reshape(shape)


def encode_lightfm_factors(values: Any) -> tuple[str, list[int]]:
    array = np.asarray(values, dtype=np.float16)
    encoded = base64.b64encode(zlib.compress(array.tobytes(), level=9)).decode("ascii")
    return encoded, list(array.shape)


def clear_lightfm_factor_cache() -> None:
    _decode_factors.cache_clear()


def live_reranker_blend_profile(query: str) -> tuple[str, float]:
    folded = fold_topic_text(query)
    discovery_markers = ("goi y", "tu van", "de xuat", "recommend", "suggest")
    generic_words = {
        "goi", "y", "tu", "van", "de", "xuat", "cho", "minh", "toi", "ban",
        "san", "pham", "phu", "hop", "giup", "gi", "do", "nao", "mot", "a",
        "the", "me", "my", "product", "products", "something", "anything",
    }
    discovery_intent = any(marker in folded for marker in discovery_markers)
    specific_terms = set(folded.split()) - generic_words
    if discovery_intent and not specific_terms:
        return "discovery", 0.65
    return "specific", 0.85


def normalize_reranker_scores(scores: dict[int, float]) -> dict[int, float]:
    finite_scores = {
        product_id: float(score)
        for product_id, score in scores.items()
        if math.isfinite(float(score))
    }
    if not finite_scores:
        return {}
    minimum = min(finite_scores.values())
    spread = max(finite_scores.values()) - minimum
    if spread <= 1e-12:
        return {product_id: 0.5 for product_id in finite_scores}
    return {
        product_id: (score - minimum) / spread
        for product_id, score in finite_scores.items()
    }


def blend_candidate_scores(
    baseline_scores: dict[int, float],
    model_scores: dict[int, float],
    *,
    baseline_weight: float,
) -> dict[int, float]:
    weight = min(1.0, max(0.0, float(baseline_weight)))
    normalized_baseline = normalize_reranker_scores(baseline_scores)
    normalized_model = normalize_reranker_scores({
        product_id: score
        for product_id, score in model_scores.items()
        if product_id in normalized_baseline
    })
    return {
        product_id: weight * baseline_score + (1.0 - weight) * normalized_model.get(product_id, baseline_score)
        for product_id, baseline_score in normalized_baseline.items()
    }

PERSONALIZED_FEATURES = frozenset({
    "affinity_score", "co_purchase_score", "interaction_score", "purchase_facet_score",
    "historic_query_overlap_score", "stated_preference_score", "color_match", "ncf_score",
    "linucb_score", "rfm_recency_log", "rfm_frequency_log", "rfm_monetary_log",
    "rag_relevance_x_rfm_recency", "rag_relevance_x_rfm_frequency",
    "rag_relevance_x_rfm_monetary", "affinity_score_x_rfm_frequency",
    "co_purchase_score_x_rfm_frequency", "interaction_score_x_rfm_frequency",
    "purchase_facet_score_x_rfm_frequency",
})


def candidate_features(
    item: dict[str, Any],
    *,
    rank: int | None = None,
    rfm_snapshot: dict[str, Any] | None = None,
    personalization_allowed: bool = False,
) -> list[float]:
    snapshot = item.get("feature_snapshot") if isinstance(item.get("feature_snapshot"), dict) else {}
    values: dict[str, float] = {
        "baseline_score": _number(item.get("score", snapshot.get("final_score"))),
        "baseline_rank": _number(rank if rank is not None else item.get("rank", item.get("position"))),
    }
    for name in FEATURE_NAMES[2:24]:
        values[name] = _number(snapshot.get(name))
    rfm_snapshot = rfm_snapshot if personalization_allowed and isinstance(rfm_snapshot, dict) else {}
    for key, name in (
        ("recency_days", "rfm_recency_log"),
        ("frequency", "rfm_frequency_log"),
        ("monetary", "rfm_monetary_log"),
    ):
        value = _number(rfm_snapshot.get(key)) if rfm_snapshot else 0.0
        values[name] = math.log1p(max(0.0, value))
    if not personalization_allowed:
        for name in PERSONALIZED_FEATURES:
            values[name] = 0.0
    values.update({
        "rag_relevance_x_rfm_recency": values["rag_relevance"] * values["rfm_recency_log"],
        "rag_relevance_x_rfm_frequency": values["rag_relevance"] * values["rfm_frequency_log"],
        "rag_relevance_x_rfm_monetary": values["rag_relevance"] * values["rfm_monetary_log"],
        "affinity_score_x_rfm_frequency": values["affinity_score"] * values["rfm_frequency_log"],
        "co_purchase_score_x_rfm_frequency": values["co_purchase_score"] * values["rfm_frequency_log"],
        "interaction_score_x_rfm_frequency": values["interaction_score"] * values["rfm_frequency_log"],
        "purchase_facet_score_x_rfm_frequency": values["purchase_facet_score"] * values["rfm_frequency_log"],
    })
    return [values.get(name, 0.0) for name in FEATURE_NAMES]


def score_candidate(
    artifact: dict[str, Any],
    item: dict[str, Any],
    *,
    rank: int,
    rfm_snapshot: dict[str, Any] | None,
    personalization_allowed: bool,
) -> float | None:
    if artifact.get("feature_names") != list(FEATURE_NAMES):
        return None
    means = artifact.get("means")
    scales = artifact.get("scales")
    weights = artifact.get("weights")
    if not all(isinstance(value, dict) for value in (means, scales, weights)):
        return None
    vector = candidate_features(
        item,
        rank=rank,
        rfm_snapshot=rfm_snapshot,
        personalization_allowed=personalization_allowed,
    )
    margin = _number(artifact.get("intercept"))
    for name, value in zip(FEATURE_NAMES, vector):
        scale = max(_number(scales.get(name), 1.0), 1e-8)
        margin += _number(weights.get(name)) * ((value - _number(means.get(name))) / scale)
    if margin >= 0:
        probability = 1.0 / (1.0 + math.exp(-min(margin, 60.0)))
    else:
        exp_margin = math.exp(max(margin, -60.0))
        probability = exp_margin / (1.0 + exp_margin)
    return probability


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default
