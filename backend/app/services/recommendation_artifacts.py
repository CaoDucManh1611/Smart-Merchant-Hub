"""Safe discovery and loading contract for offline recommendation artifacts.

The Colab artifacts are useful for a warm-start/demo, but they were trained
on public UCI identifiers.  This registry therefore exposes their presence
without silently applying them to a tenant with unrelated CRM identifiers.
Production artifacts must carry a tenant-specific manifest and a separate,
tenant-scoped loader. This module intentionally implements only the explicit
``demo`` mode for the imported public checkpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from pathlib import Path
from typing import Any

from app.core.config import settings


@dataclass(frozen=True)
class ArtifactSpec:
    key: str
    relative_path: str
    algorithm: str
    source_dataset: str
    allowed_mode: str


ARTIFACT_SPECS = (
    ArtifactSpec(
        key="unsupervised_segmentation",
        relative_path="unsupervised/uci_customer_segmentation.joblib",
        algorithm="KMeans customer segmentation",
        source_dataset="public_uci",
        allowed_mode="demo",
    ),
    ArtifactSpec(
        key="reinforcement_policy",
        relative_path="reinforcement/linucb_bandit_state.joblib",
        algorithm="disjoint LinUCB contextual bandit",
        source_dataset="public_uci_proxy_events",
        allowed_mode="demo",
    ),
    ArtifactSpec(
        key="deep_learning_ncf",
        relative_path="deep_learning/ncf_best.pt",
        algorithm="NCF with BPR pairwise ranking loss",
        source_dataset="public_uci",
        allowed_mode="demo",
    ),
)


class RecommendationArtifactError(RuntimeError):
    pass


class RecommendationArtifactRegistry:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or settings.RECOMMENDATION_ARTIFACT_DIR).resolve()

    def _path(self, spec: ArtifactSpec) -> Path:
        return self.root / spec.relative_path

    def status(self) -> dict[str, Any]:
        mode = str(settings.RECOMMENDATION_ARTIFACT_MODE or "fallback").strip().lower()
        entries = []
        for spec in ARTIFACT_SPECS:
            path = self._path(spec)
            present = path.is_file()
            enabled = present and mode == spec.allowed_mode
            entries.append(
                {
                    "key": spec.key,
                    "path": spec.relative_path,
                    "algorithm": spec.algorithm,
                    "source_dataset": spec.source_dataset,
                    "present": present,
                    "enabled": enabled,
                    "reason": (
                        "ready_for_demo_only"
                        if enabled
                        else "missing_artifact"
                        if not present
                        else "disabled_or_dataset_scope_mismatch"
                    ),
                }
            )
        return {"mode": mode, "artifacts": entries}

    def require_demo_artifact(self, key: str) -> Path:
        mode = str(settings.RECOMMENDATION_ARTIFACT_MODE or "fallback").strip().lower()
        spec = next((item for item in ARTIFACT_SPECS if item.key == key), None)
        if spec is None:
            raise RecommendationArtifactError(f"Unknown recommendation artifact: {key}")
        path = self._path(spec)
        if mode != spec.allowed_mode:
            raise RecommendationArtifactError(
                f"Artifact {key} is public-dataset-only and is not enabled in mode {mode!r}."
            )
        if not path.is_file():
            raise RecommendationArtifactError(f"Artifact file is missing: {path}")
        return path

    def demo_segmentation_label(self, features: dict[str, float]) -> int | None:
        """Return the public checkpoint's cluster only in explicit demo mode."""
        try:
            path = self.require_demo_artifact("unsupervised_segmentation")
        except RecommendationArtifactError:
            return None
        bundle = _load_joblib(path)
        feature_names = bundle.get("features") if isinstance(bundle, dict) else None
        scaler = bundle.get("scaler") if isinstance(bundle, dict) else None
        model = bundle.get("model") if isinstance(bundle, dict) else None
        if not isinstance(feature_names, list) or scaler is None or model is None:
            raise RecommendationArtifactError("Invalid UCI segmentation artifact contract.")
        try:
            vector = [[float(features[name]) for name in feature_names]]
            return int(model.predict(scaler.transform(vector))[0])
        except (KeyError, TypeError, ValueError) as exc:
            raise RecommendationArtifactError("Cannot build the UCI segmentation feature vector.") from exc

    def demo_linucb_scores(self, candidate_skus: list[str], features: dict[str, float], segment_label: int | None) -> dict[str, float]:
        """Score only SKUs that have an exact public-dataset arm mapping."""
        try:
            path = self.require_demo_artifact("reinforcement_policy")
        except RecommendationArtifactError:
            return {}
        bundle = _load_joblib(path)
        if not isinstance(bundle, dict):
            raise RecommendationArtifactError("Invalid LinUCB artifact contract.")
        feature_definition = bundle.get("feature_definition")
        arm_ids = bundle.get("arm_ids")
        matrices_a = bundle.get("A")
        vectors_b = bundle.get("b")
        alpha = float(bundle.get("alpha", 0.0))
        if not all(value is not None for value in (feature_definition, arm_ids, matrices_a, vectors_b)):
            raise RecommendationArtifactError("LinUCB artifact is missing matrices or feature metadata.")
        context = _linucb_context(feature_definition, features, segment_label)
        arm_index = {str(arm): index for index, arm in enumerate(arm_ids)}
        raw_scores: dict[str, float] = {}
        for sku in candidate_skus:
            index = arm_index.get(str(sku))
            if index is None:
                continue
            raw_scores[str(sku)] = _linucb_ucb(matrices_a[index], vectors_b[index], context, alpha)
        return _min_max_scale(raw_scores)

    def demo_ncf_scores(self, customer_id: int | None, candidate_skus: list[str]) -> dict[str, float]:
        """Rerank exact UCI customer/SKU mappings from the NCF checkpoint.

        A CRM tenant normally has different identifiers, so an empty mapping is
        an expected and safe result outside the demo dataset.
        """
        if customer_id is None:
            return {}
        try:
            path = self.require_demo_artifact("deep_learning_ncf")
        except RecommendationArtifactError:
            return {}
        checkpoint = _load_ncf_checkpoint(path)
        user_to_idx = checkpoint.get("user_to_idx", {})
        item_to_idx = checkpoint.get("item_to_idx", {})
        user_index = user_to_idx.get(str(customer_id))
        if user_index is None:
            return {}
        valid_skus = [str(sku) for sku in candidate_skus if str(sku) in item_to_idx]
        if not valid_skus:
            return {}
        torch = _torch()
        model = _ncf_model_for_path(path)
        users = torch.full((len(valid_skus),), int(user_index), dtype=torch.long)
        items = torch.tensor([int(item_to_idx[sku]) for sku in valid_skus], dtype=torch.long)
        with torch.no_grad():
            values = torch.sigmoid(model(users, items)).tolist()
        return _min_max_scale({sku: float(value) for sku, value in zip(valid_skus, values)})


registry = RecommendationArtifactRegistry()


def recommendation_artifact_status() -> dict[str, Any]:
    return registry.status()


@lru_cache(maxsize=8)
def _load_joblib(path: Path) -> Any:
    try:
        import joblib
    except ImportError as exc:  # pragma: no cover - installation failure is operational
        raise RecommendationArtifactError("joblib/scikit-learn is required to load recommendation artifacts.") from exc
    return joblib.load(path)


@lru_cache(maxsize=4)
def _load_ncf_checkpoint(path: Path) -> dict[str, Any]:
    torch = _torch()
    try:
        checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    except Exception as exc:  # pragma: no cover - depends on external checkpoint bytes
        raise RecommendationArtifactError("Cannot load NCF checkpoint with safe weights-only mode.") from exc
    required = {"user_to_idx", "item_to_idx", "model_state_dict", "n_users", "n_items", "embedding_dim"}
    if not isinstance(checkpoint, dict) or not required.issubset(checkpoint):
        raise RecommendationArtifactError("Invalid NCF checkpoint contract.")
    return checkpoint


def _torch():
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - installation failure is operational
        raise RecommendationArtifactError("PyTorch is required to load the NCF checkpoint.") from exc
    return torch


@lru_cache(maxsize=4)
def _ncf_model_for_path(path: Path):
    """Rebuild the architecture stored in the Colab state dict, then load it strictly."""
    torch = _torch()
    checkpoint = _load_ncf_checkpoint(path)

    class NcfBpr(torch.nn.Module):
        def __init__(self, n_users: int, n_items: int, embedding_dim: int):
            super().__init__()
            self.user_embedding = torch.nn.Embedding(n_users, embedding_dim)
            self.item_embedding = torch.nn.Embedding(n_items, embedding_dim)
            self.layers = torch.nn.Sequential(
                torch.nn.Linear(embedding_dim * 2, 64),
                torch.nn.ReLU(),
                torch.nn.Dropout(0.1),
                torch.nn.Linear(64, 32),
                torch.nn.ReLU(),
                torch.nn.Linear(32, 1),
            )

        def forward(self, users, items):
            features = torch.cat((self.user_embedding(users), self.item_embedding(items)), dim=1)
            return self.layers(features).squeeze(-1)

    model = NcfBpr(int(checkpoint["n_users"]), int(checkpoint["n_items"]), int(checkpoint["embedding_dim"]))
    model.load_state_dict(checkpoint["model_state_dict"], strict=True)
    model.eval()
    return model


def _linucb_context(feature_definition: list[str], features: dict[str, float], segment_label: int | None):
    values = {
        "bias": 1.0,
        "recency_inverse": 1.0 / (1.0 + max(0.0, float(features.get("recency_days", 365.0)))),
        "log_frequency": math.log1p(max(0.0, float(features.get("frequency", 0.0)))),
        "log_monetary": math.log1p(max(0.0, float(features.get("monetary", 0.0)))),
        "log_distinct_products": math.log1p(max(0.0, float(features.get("distinct_products", 0.0)))),
        "log_avg_order_value": math.log1p(max(0.0, float(features.get("avg_order_value", 0.0)))),
        "segment_one_hot": 1.0 if segment_label == 0 else 0.0,
    }
    return [float(values.get(str(name), 0.0)) for name in feature_definition]


def _linucb_ucb(matrix_a, vector_b, context: list[float], alpha: float) -> float:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - numpy is transitive for scikit-learn
        raise RecommendationArtifactError("NumPy is required to score LinUCB.") from exc
    vector = np.asarray(context, dtype=float)
    matrix = np.asarray(matrix_a, dtype=float)
    rewards = np.asarray(vector_b, dtype=float)
    theta = np.linalg.solve(matrix, rewards)
    uncertainty = math.sqrt(max(0.0, float(vector @ np.linalg.solve(matrix, vector))))
    return float(theta @ vector + alpha * uncertainty)


def _min_max_scale(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    low, high = min(scores.values()), max(scores.values())
    if math.isclose(low, high):
        return {key: 1.0 for key in scores}
    return {key: (value - low) / (high - low) for key, value in scores.items()}
