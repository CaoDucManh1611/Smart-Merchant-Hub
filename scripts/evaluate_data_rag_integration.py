#!/usr/bin/env python3
"""Evaluate the installed portable Data_RAG models on their synthetic holdout."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.recommendation_artifacts import RecommendationArtifactRegistry


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--training-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "data-rag-integration-report.json")
    args = parser.parse_args()
    from train_data_rag_local import load_conversation_context, read_csv_rows

    dataset = args.dataset.resolve()
    run = args.training_run.resolve()
    artifact_registry = RecommendationArtifactRegistry(ROOT / "backend" / "artifacts")
    contexts, _, _ = load_conversation_context(dataset / "conversations.jsonl")
    products = {}
    for row in read_csv_rows(dataset / "products.csv"):
        product = SimpleNamespace(
            id=int(row["product_id"]), sku=row["sku"], name=row["name"],
            price=float(row["price"] or 0), stock_quantity=int(row["stock"] or 0),
            reserved_quantity=0,
            metadata_={"color": row.get("color", ""), "category": row.get("category", "")},
        )
        products[str(row["product_id"])] = product

    groups: dict[str, list[dict]] = defaultdict(list)
    for row in read_csv_rows(dataset / "interactions.csv"):
        if row["split"] == "test":
            groups[row["conversation_id"]].append(row)
    ranks = []
    baseline = []
    evaluated = 0
    malformed = 0
    for conversation_id, rows in groups.items():
        context = contexts[conversation_id]
        if len(rows) != 3 or sum(row["event"] != "impression" for row in rows) != 1:
            malformed += 1
            continue
        rows.sort(key=lambda row: int(row["position"]))
        candidates = [products[row["product_id"]] for row in rows]
        scores = artifact_registry.data_rag_scores(
            0, candidates, context["pre_recommendation_text"], preview=True,
        )
        target_id = int(next(row["product_id"] for row in rows if row["event"] != "impression"))
        baseline_position = {product.id: index for index, product in enumerate(candidates)}
        ranked = sorted(candidates, key=lambda product: (-scores[product.id], baseline_position[product.id]))
        ranks.append(next(i + 1 for i, product in enumerate(ranked) if product.id == target_id))
        baseline.append(next(i + 1 for i, row in enumerate(rows) if int(row["product_id"]) == target_id))
        evaluated += 1

    assignments = list(read_csv_rows(run / "rfm_assignments.csv"))
    matched = 0
    buyers = [row for row in assignments if int(row["frequency_completed_orders"]) > 0]
    for row in buyers:
        predicted = artifact_registry.data_rag_segment(0, {
            "recency_days": float(row["recency_days"]),
            "frequency": float(row["frequency_completed_orders"]),
            "monetary": float(row["monetary_completed_orders"]),
        }, preview=True)
        matched += int(predicted == int(row["cluster_id"]))
    nonbuyers = [row for row in assignments if int(row["frequency_completed_orders"]) == 0]
    new_customer_safe = all(artifact_registry.data_rag_segment(0, {
        "recency_days": float(row["recency_days"]), "frequency": 0,
        "monetary": float(row["monetary_completed_orders"]),
    }, preview=True) is None for row in nonbuyers)

    def metrics(values: list[int]) -> dict:
        total = len(values)
        return {
            "conversations": total,
            "hit_at_1": sum(rank == 1 for rank in values) / total if total else 0,
            "hit_at_2": sum(rank <= 2 for rank in values) / total if total else 0,
            "mrr_at_3": sum(1 / rank for rank in values) / total if total else 0,
        }

    report = {
        "status": "completed" if evaluated == 10000 and malformed == 0 and len(assignments) == 10000 else "incomplete",
        "data_scope": "synthetic offline Data_RAG holdout only; no real shop or customer data",
        "product_ranking": {
            "target_definition": "non-impression product interaction; a choice proxy, not a purchase/conversion label",
            "model": metrics(ranks), "position_baseline": metrics(baseline),
            "model_source": "installed portable JSON checkpoint; same three-candidate limit as training",
            "malformed_test_conversations": malformed,
        },
        "rfm": {
            "customers": len(assignments), "buyers": len(buyers), "no_completed_order_customers": len(nonbuyers),
            "portable_checkpoint_cluster_match": matched / len(buyers) if buyers else 0,
            "portable_checkpoint_cluster_match_count": matched,
            "new_customers_not_forced_into_buyer_cluster": new_customer_safe,
            "labels_are_arbitrary": True,
        },
        "limitations": [
            "Synthetic ranking labels indicate a non-impression interaction, not an order or revenue outcome.",
            "RFM cluster IDs are mathematical groups and need shop-specific interpretation before customer-facing use.",
            "This evaluates model loading and holdout behavior; it does not certify real-shop relevance or conversion lift.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
