#!/usr/bin/env python3
"""Build privacy-safe cold-start RFM centroids from audited public profiles."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.cluster import MiniBatchKMeans
from sklearn.metrics import silhouette_score


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.industry_rfm_prior import (  # noqa: E402
    INDUSTRY_RFM_PRIOR_ALGORITHM,
    INDUSTRY_RFM_PRIOR_VERSION,
    semantic_labels_for_prior_centers,
)


SOURCE_GROUPS = {
    "cross_industry": ["dunnhumby", "hm", "olist", "online_retail", "online_retail_ii"],
    "general_retail": ["olist", "online_retail", "online_retail_ii"],
    "fashion": ["hm"],
    "grocery": ["dunnhumby"],
    "ecommerce": ["olist", "online_retail", "online_retail_ii"],
}
RECENCY_CUTOFFS = [7, 30, 90, 180]
FREQUENCY_CUTOFFS = [1, 2, 5, 10]
RELATIVE_MONETARY_CUTOFFS = [0.5, 0.8, 1.2, 2.0]
RANDOM_STATE = 20261103


def _quantized_score(value: float, cutoffs: list[float], *, lower_is_better: bool = False) -> int:
    score = 1 + sum(value > cutoff for cutoff in cutoffs)
    return 6 - score if lower_is_better else score


def _load_sample(models_root: Path, source: str, max_profiles: int) -> tuple[list[list[float]], dict]:
    source_root = models_root / source
    run_dirs = sorted((path for path in source_root.glob("run_*") if path.is_dir()), key=lambda path: path.name, reverse=True)
    if not run_dirs:
        raise FileNotFoundError(f"No trained run for source {source} under {source_root}")
    run_dir = run_dirs[0]
    profiles_path = run_dir / "rfm_profiles.csv"
    report_path = run_dir / "training_report.json"
    if not profiles_path.is_file() or not report_path.is_file():
        raise FileNotFoundError(f"Missing profile/report for {source}: {run_dir}")
    with report_path.open("r", encoding="utf-8") as stream:
        report = json.load(stream)
    rows: list[tuple[float, float, float]] = []
    monetary_values: list[float] = []
    rng = random.Random(RANDOM_STATE + sum(ord(char) for char in source))
    with profiles_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        expected = {"recency_days", "frequency", "monetary"}
        if not expected.issubset(set(reader.fieldnames or [])):
            raise ValueError(f"RFM profile schema mismatch for {source}: {reader.fieldnames}")
        for row in reader:
            try:
                recency = max(0.0, float(row["recency_days"]))
                frequency = max(0.0, float(row["frequency"]))
                monetary = max(0.0, float(row["monetary"]))
            except (TypeError, ValueError):
                continue
            if frequency <= 0 or monetary <= 0:
                continue
            monetary_values.append(monetary)
            item = (recency, frequency, monetary)
            if len(rows) < max_profiles:
                rows.append(item)
            else:
                index = rng.randrange(len(monetary_values))
                if index < max_profiles:
                    rows[index] = item
    if not rows or not monetary_values:
        raise ValueError(f"No complete RFM buyer profiles for {source}")
    median_monetary = float(statistics.median(monetary_values))
    vectors = []
    for recency, frequency, monetary in rows:
        relative_monetary = monetary / median_monetary if median_monetary > 0 else 1.0
        vectors.append([
            _quantized_score(recency, RECENCY_CUTOFFS, lower_is_better=True),
            _quantized_score(frequency, FREQUENCY_CUTOFFS),
            _quantized_score(relative_monetary, RELATIVE_MONETARY_CUTOFFS),
        ])
    quality = ((report.get("rfm") or {}).get("quality") or {})
    source_info = {
        "source": source,
        "training_run": run_dir.name,
        "profile_rows_seen": len(monetary_values),
        "profiles_sampled": len(rows),
        "source_rfm_silhouette": quality.get("silhouette_score"),
    }
    return vectors, source_info


def _fit_model(models_root: Path, key: str, sources: list[str], max_profiles: int) -> dict:
    matrices = []
    source_info = []
    for source in sources:
        vectors, info = _load_sample(models_root, source, max_profiles)
        matrices.append(np.asarray(vectors, dtype=np.float32))
        source_info.append(info)
    matrix = np.concatenate(matrices, axis=0)
    cluster_count = min(4, len(matrix))
    model = MiniBatchKMeans(
        n_clusters=cluster_count,
        random_state=RANDOM_STATE,
        n_init=10,
        max_iter=200,
        batch_size=min(2048, max(128, cluster_count * 64)),
        reassignment_ratio=0.01,
    )
    labels = model.fit_predict(matrix)
    centers = [[round(float(value), 6) for value in center] for center in model.cluster_centers_]
    cluster_sizes = {str(int(cluster)): int(count) for cluster, count in zip(*np.unique(labels, return_counts=True))}
    sample_size = min(5000, len(matrix))
    silhouette = None
    if 1 < len(cluster_sizes) < len(matrix):
        silhouette = round(float(silhouette_score(
            matrix,
            labels,
            sample_size=sample_size,
            random_state=RANDOM_STATE,
        )), 6)
    return {
        "model_key": key,
        "algorithm": INDUSTRY_RFM_PRIOR_ALGORITHM,
        "features": ["recency_score_1_to_5", "frequency_score_1_to_5", "relative_monetary_score_1_to_5"],
        "centers": centers,
        "cluster_segment_labels": semantic_labels_for_prior_centers(centers),
        "training_profiles": int(len(matrix)),
        "cluster_sizes": cluster_sizes,
        "silhouette_sample_size": sample_size if silhouette is not None else 0,
        "silhouette_score": silhouette,
        "source_datasets": source_info,
        "training_method": "balanced_per_source_sample + MiniBatchKMeans on normalized ordinal RFM scores",
    }


def build(models_root: Path, output_dir: Path, max_profiles: int) -> dict:
    models = {
        key: _fit_model(models_root, key, sources, max_profiles)
        for key, sources in SOURCE_GROUPS.items()
    }
    bundle = {
        "model_version": INDUSTRY_RFM_PRIOR_VERSION,
        "algorithm": INDUSTRY_RFM_PRIOR_ALGORITHM,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "privacy": {
            "contains_customer_ids": False,
            "contains_transaction_rows": False,
            "contents": "RFM cutoffs and cluster centroids only",
        },
        "feature_contract": {
            "recency_days_cutoffs": RECENCY_CUTOFFS,
            "frequency_order_count_cutoffs": FREQUENCY_CUTOFFS,
            "relative_monetary_cutoffs": RELATIVE_MONETARY_CUTOFFS,
            "monetary_normalization": "customer lifetime net spend divided by median lifetime net spend of this shop's consented buyers; neutral score when peer baseline is unavailable",
            "no_purchase": "not clustered; remains the explicit no_purchase segment",
        },
        "industry_aliases": {"services": "cross_industry", "b2b": "cross_industry", "mixed": "cross_industry"},
        "models": models,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "prior_model.json"
    serialized = json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    model_path.write_text(serialized, encoding="utf-8")
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    manifest = {
        "model_version": INDUSTRY_RFM_PRIOR_VERSION,
        "sha256": {model_path.name: digest},
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"model_file": str(model_path), "sha256": digest, "models": {
        key: {"training_profiles": value["training_profiles"], "sources": value["source_datasets"]}
        for key, value in models.items()
    }}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-root", type=Path, default=Path(r"D:\CRM_Industry_Datasets\training_audit_runs\run_20261103_142300\models"))
    parser.add_argument("--output-dir", type=Path, default=BACKEND_ROOT / "artifacts" / "industry_rfm")
    parser.add_argument("--max-profiles-per-source", type=int, default=20000)
    args = parser.parse_args()
    report = build(args.models_root, args.output_dir, max(100, args.max_profiles_per_source))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
