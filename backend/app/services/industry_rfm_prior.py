"""Cross-shop cold-start RFM priors built from privacy-safe public aggregates.

The prior contains only cluster centroids and fixed feature cutoffs. It never
loads public customer identifiers or transaction rows at serving time.
"""

from __future__ import annotations

import json
import hashlib
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.rfm_segments import RFM_SEGMENT_KEYS, rfm_group


INDUSTRY_RFM_PRIOR_VERSION = "industry_rfm_cold_start_v1"
INDUSTRY_RFM_PRIOR_ALGORITHM = "balanced_public_rfm_centroid_prior"
INDUSTRY_PRIOR_PATH = Path("industry_rfm") / "prior_model.json"
# Resolve this while the backend package is imported. Test runners and worker
# jobs may change CWD later, and some import configurations keep __file__
# relative; resolving it inside _artifact_path() would then point at that CWD.
BACKEND_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
INDUSTRY_MODEL_KEYS = {
    "cross_industry", "general_retail", "fashion", "grocery", "ecommerce",
    "services", "b2b", "mixed",
}
MODEL_ALIASES = {"services": "cross_industry", "b2b": "cross_industry", "mixed": "cross_industry"}


class IndustryRfmPriorUnavailable(RuntimeError):
    pass


def _artifact_path() -> Path:
    root = Path(settings.RECOMMENDATION_ARTIFACT_DIR)
    if not root.is_absolute():
        # Relative artifact configuration is rooted at the backend package,
        # never at the process CWD (which differs between CLI, workers, and tests).
        root = BACKEND_PACKAGE_ROOT / root
    return (root / INDUSTRY_PRIOR_PATH).resolve()


@lru_cache(maxsize=1)
def load_industry_rfm_prior() -> dict[str, Any]:
    path = _artifact_path()
    try:
        raw = path.read_bytes()
        manifest = json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("model_version") != INDUSTRY_RFM_PRIOR_VERSION:
            raise IndustryRfmPriorUnavailable("Industry RFM prior manifest version mismatch.")
        expected_hash = manifest.get("sha256", {}).get(path.name)
        if not expected_hash or hashlib.sha256(raw).hexdigest() != expected_hash:
            raise IndustryRfmPriorUnavailable("Industry RFM prior checksum mismatch.")
        bundle = json.loads(raw)
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise IndustryRfmPriorUnavailable(f"Industry RFM prior is not available at {path}.") from exc
    if bundle.get("model_version") != INDUSTRY_RFM_PRIOR_VERSION:
        raise IndustryRfmPriorUnavailable("Industry RFM prior version mismatch.")
    models = bundle.get("models")
    if not isinstance(models, dict):
        raise IndustryRfmPriorUnavailable("Industry RFM prior has no model registry.")
    for key in ("cross_industry", "general_retail", "fashion", "grocery", "ecommerce"):
        model = models.get(key)
        centers = model.get("centers") if isinstance(model, dict) else None
        if not isinstance(centers, list) or not centers or any(
            not isinstance(center, list) or len(center) != 3
            or not all(math.isfinite(float(value)) for value in center)
            for center in centers
        ):
            raise IndustryRfmPriorUnavailable(f"Invalid RFM prior centroids for {key}.")
    return bundle


def industry_rfm_prior_status() -> dict[str, Any]:
    try:
        bundle = load_industry_rfm_prior()
    except IndustryRfmPriorUnavailable as exc:
        return {"available": False, "model_version": INDUSTRY_RFM_PRIOR_VERSION, "reason": str(exc)}
    return {
        "available": True,
        "model_version": INDUSTRY_RFM_PRIOR_VERSION,
        "algorithm": INDUSTRY_RFM_PRIOR_ALGORITHM,
        "industries": sorted(bundle["models"]),
    }


def _bounded_score(value: float, cutoffs: list[float], *, reverse: bool = False) -> int:
    score = 1 + sum(float(value) > float(cutoff) for cutoff in cutoffs)
    return 6 - score if reverse else score


def _rfm_score_vector(features: dict[str, Any], *, peer_median_monetary: float | None) -> list[int]:
    recency = max(0.0, float(features.get("recency_days") or 0))
    frequency = max(0.0, float(features.get("frequency") or 0))
    monetary = max(0.0, float(features.get("monetary") or 0))
    recency_score = _bounded_score(recency, [7, 30, 90, 180], reverse=True)
    frequency_score = _bounded_score(frequency, [1, 2, 5, 10])
    # Monetary is expressed relative to the shop's consented buyer population,
    # so currency and public-dataset units cannot leak into the live score.
    if peer_median_monetary is None or peer_median_monetary <= 0 or monetary <= 0:
        monetary_score = 3
    else:
        relative_monetary = monetary / peer_median_monetary
        monetary_score = _bounded_score(relative_monetary, [0.5, 0.8, 1.2, 2.0])
    return [recency_score, frequency_score, monetary_score]


def predict_industry_rfm_prior(
    features: dict[str, Any],
    *,
    industry: str,
    peer_median_monetary: float | None,
    consented_buyer_count: int,
) -> dict[str, Any] | None:
    """Assign an RFM cluster using the selected industry prior.

    No-purchase customers intentionally remain in the explicit no-purchase
    bucket; a transaction-based model cannot infer product affinity for them.
    """
    if int(features.get("frequency") or 0) <= 0:
        return None
    bundle = load_industry_rfm_prior()
    selected = industry if industry in INDUSTRY_MODEL_KEYS else "cross_industry"
    model_key = MODEL_ALIASES.get(selected, selected)
    model = bundle["models"].get(model_key) or bundle["models"]["cross_industry"]
    vector = _rfm_score_vector(features, peer_median_monetary=peer_median_monetary)
    centers = model["centers"]
    cluster_id = min(
        range(len(centers)),
        key=lambda index: sum((float(value) - float(center)) ** 2 for value, center in zip(vector, centers[index])),
    )
    label = model["cluster_segment_labels"][str(cluster_id)]
    segment_name = next((name for name, key in RFM_SEGMENT_KEYS.items() if key == label), "RFM · Duy trì")
    buyer_count = max(0, int(consented_buyer_count))
    confidence = "low" if buyer_count < 5 else "medium" if buyer_count < 20 else "high"
    return {
        "cluster_id": int(cluster_id),
        "cluster_model_version": INDUSTRY_RFM_PRIOR_VERSION,
        "cluster_model_source": "industry_prior",
        "cluster_model_industry": selected,
        "cluster_model_backing": model_key,
        "recommendation_segment_label": label,
        "recommendation_segment_name": segment_name,
        "rfm_scores": {"recency": vector[0], "frequency": vector[1], "monetary": vector[2]},
        "rfm_model_confidence": confidence,
        "rfm_model_consent_peer_count": buyer_count,
    }


def semantic_labels_for_centers(centers: list[list[float]]) -> dict[str, str]:
    """Map scaled shop-model centroids to the existing explainable RFM groups."""
    labels: dict[str, str] = {}
    for index, center in enumerate(centers):
        recency = max(1, min(5, round(3 - float(center[0]))))
        frequency = max(1, min(5, round(3 + float(center[1]))))
        monetary = max(1, min(5, round(3 + float(center[2]))))
        name = rfm_group(recency, frequency, monetary)
        labels[str(index)] = RFM_SEGMENT_KEYS[name]
    return labels


def semantic_labels_for_prior_centers(centers: list[list[float]]) -> dict[str, str]:
    """Map already-quantized 1-to-5 RFM centroids to existing business labels."""
    labels: dict[str, str] = {}
    for index, center in enumerate(centers):
        recency, frequency, monetary = (
            max(1, min(5, round(float(value)))) for value in center
        )
        labels[str(index)] = RFM_SEGMENT_KEYS[rfm_group(recency, frequency, monetary)]
    return labels
