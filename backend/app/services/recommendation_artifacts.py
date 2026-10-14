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
import hashlib
import json
import math
import re
import unicodedata
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
    ArtifactSpec("data_rag_ranker", "data_rag/product_choice_ranker.json", "LogisticRegression product choice", "synthetic_data_rag", "demo"),
    ArtifactSpec("data_rag_rfm", "data_rag/rfm_kmeans.json", "KMeans log-RFM segmentation", "synthetic_data_rag", "demo"),
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

    def data_rag_enabled(self, business_id: int) -> bool:
        allowed = {int(value) for value in settings.RECOMMENDATION_DATA_RAG_BUSINESS_IDS.split(",") if value.strip().isdigit()}
        return settings.RECOMMENDATION_ARTIFACT_MODE == "demo" and business_id in allowed

    def _data_rag_bundle(self, key: str, *, preview: bool = False):
        spec = next(spec for spec in ARTIFACT_SPECS if spec.key == key)
        path = self._path(spec) if preview else self.require_demo_artifact(key)
        return self._read_data_rag_json(path)

    def data_rag_asset(self, name: str) -> dict | list:
        if name not in {"catalog.json", "training_report.json"}:
            raise RecommendationArtifactError("Unsupported Data_RAG preview asset.")
        return self._read_data_rag_json(self.root / "data_rag" / name)

    def _read_data_rag_json(self, path: Path) -> dict | list:
        try:
            manifest = json.loads((self.root / "data_rag" / "manifest.json").read_text(encoding="utf-8"))
            expected = manifest["sha256"][path.name]
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise RecommendationArtifactError("Data_RAG checkpoint checksum mismatch.")
        except (OSError, KeyError, ValueError) as exc:
            raise RecommendationArtifactError("Data_RAG manifest is missing or invalid.") from exc
        return json.loads(path.read_text(encoding="utf-8"))

    def data_rag_scores(self, business_id: int, products: list, query: str | None, *, preview: bool = False) -> dict[int, float]:
        if (not preview and not self.data_rag_enabled(business_id)) or not products:
            return {}
        bundle = self._data_rag_bundle("data_rag_ranker", preview=preview)
        if bundle.get("features") != DATA_RAG_FEATURES:
            raise RecommendationArtifactError("Data_RAG ranking feature contract mismatch.")
        products = products[:3]  # Checkpoint was trained on three displayed candidates only.
        features = [data_rag_candidate_features(query or "", product, index) for index, product in enumerate(products, 1)]
        scores = []
        for vector in features:
            normalized = _standardize_data_rag(vector, bundle)
            weights = bundle["weights"]
            if len(weights) != len(normalized):
                raise RecommendationArtifactError("Data_RAG ranking coefficients do not match features.")
            z = sum(x * float(w) for x, w in zip(normalized, weights)) + float(bundle["intercept"])
            if not math.isfinite(z):
                raise RecommendationArtifactError("Non-finite Data_RAG ranking result.")
            scores.append(1 / (1 + math.exp(-max(-700, min(700, z)))))
        return {int(product.id): float(score) for product, score in zip(products, scores)}

    def data_rag_segment(self, business_id: int, features: dict[str, float], *, preview: bool = False) -> int | None:
        if (not preview and not self.data_rag_enabled(business_id)) or features.get("frequency", 0) <= 0:
            return None
        bundle = self._data_rag_bundle("data_rag_rfm", preview=preview)
        if bundle.get("features") != ["log_recency_days", "log_frequency", "log_monetary", "has_completed_order"]:
            raise RecommendationArtifactError("Data_RAG RFM feature contract mismatch.")
        vector = [[math.log1p(max(0, features["recency_days"])), math.log1p(max(0, features["frequency"])),
                   math.log1p(max(0, features["monetary"])), 1.0]]
        normalized = _standardize_data_rag(vector[0], bundle)
        centers = bundle["centers"]
        if not centers or any(len(center) != len(normalized) or not all(math.isfinite(float(x)) for x in center) for center in centers):
            raise RecommendationArtifactError("Invalid Data_RAG cluster centers.")
        return min(range(len(centers)), key=lambda i: sum((x - float(c)) ** 2 for x, c in zip(normalized, centers[i])))

    def status(self) -> dict[str, Any]:
        mode = str(settings.RECOMMENDATION_ARTIFACT_MODE or "fallback").strip().lower()
        entries = []
        for spec in ARTIFACT_SPECS:
            path = self._path(spec)
            present = path.is_file()
            enabled = present and mode == spec.allowed_mode and (
                spec.source_dataset != "synthetic_data_rag" or bool(settings.RECOMMENDATION_DATA_RAG_BUSINESS_IDS.strip())
            )
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

def _standardize_data_rag(vector: list[float], bundle: dict) -> list[float]:
    means, scales = bundle["mean"], bundle["scale"]
    if len(vector) != len(means) or len(vector) != len(scales):
        raise RecommendationArtifactError("Data_RAG scaler dimensions do not match features.")
    if not all(math.isfinite(float(v)) for v in [*vector, *means, *scales]) or any(float(s) <= 0 for s in scales):
        raise RecommendationArtifactError("Invalid Data_RAG scaler values.")
    return [(float(x) - float(m)) / float(s) for x, m, s in zip(vector, means, scales)]


DATA_RAG_FEATURES = [
    "position", "log_price", "log_stock", "in_stock", "has_budget", "within_budget",
    "price_to_budget", "candidate_color_mentioned", "candidate_category_mentioned",
]


def data_rag_normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def stated_budget(query: str) -> float | None:
    matches = list(re.finditer(
        r"(?:tầm|khoảng|dưới|tối đa|ngân sách|budget|under|up to|<=|≤)\s*"
        r"(\d{1,3}(?:[.,]\d{3})*|\d+(?:[.,]\d+)?)\s*(k|nghìn|ngàn|tr|triệu|đồng|đ|vnd)?\b",
        query, re.I,
    ))
    if not matches:
        return None
    number, suffix = matches[-1].group(1), (matches[-1].group(2) or "").casefold()
    parts = re.split(r"[.,]", number)
    value = float("".join(parts) if len(parts) > 1 and len(parts[-1]) == 3 else number.replace(",", "."))
    return value * (1000 if suffix in {"k", "nghìn", "ngàn"} else 1000000 if suffix in {"tr", "triệu"} else 1)


def data_rag_candidate_features(query: str, product, position: int) -> list[float]:
    """Exact nine features of scripts/train_data_rag_local.py, before any reply."""
    text = data_rag_normalize(query)
    metadata = product.metadata_ if isinstance(product.metadata_, dict) else {}
    price = max(0.0, float(product.price or 0))
    stock = max(0, int(product.stock_quantity or 0) - int(product.reserved_quantity or 0))
    budget = stated_budget(text)
    color = data_rag_normalize(str(metadata.get("color") or ""))
    category = data_rag_normalize(str(metadata.get("category") or ""))
    has_budget = budget is not None and budget > 0
    return [
        float(position), math.log1p(price), math.log1p(stock), float(stock > 0),
        float(has_budget), float(has_budget and price <= budget), price / budget if has_budget else 1.0,
        float(bool(color) and color in text), float(bool(category) and category in text),
    ]



def recommendation_artifact_status() -> dict[str, Any]:
    return registry.status()


@lru_cache(maxsize=8)
def _load_joblib(path: Path) -> Any:
    try:
        import joblib
    except ImportError as exc:  # pragma: no cover - installation failure is operational
        raise RecommendationArtifactError("joblib/scikit-learn is required to load recommendation artifacts.") from exc
    try:
        return joblib.load(path)
    except Exception as exc:
        raise RecommendationArtifactError("Cannot load the trusted recommendation checkpoint.") from exc


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
