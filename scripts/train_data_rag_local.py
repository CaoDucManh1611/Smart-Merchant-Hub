#!/usr/bin/env python3
"""Train a small synthetic product-ranker and RFM segmentation model locally.

This intentionally does not fine-tune a chatbot. It uses only the supplied
synthetic conversations, interaction log, catalog, customers, and train-split
completed orders. evaluation_truth.csv is never opened.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.cluster import KMeans
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


FEATURE_NAMES = [
    "position",
    "log_price",
    "log_stock",
    "in_stock",
    "has_budget",
    "within_budget",
    "price_to_budget",
    "candidate_color_mentioned",
    "candidate_category_mentioned",
]
TRAIN_SPLIT = "train"
SPLITS = ("train", "validation", "test")
PROGRESS_INTERVAL = 25_000
INTERACTION_PROGRESS_INTERVAL = 100_000

_BUDGET_RE = re.compile(
    r"(?:tầm|khoảng|dưới|tối đa|ngân sách|budget|<=|≤)\s*"
    r"(\d{1,3}(?:[.,]\d{3})*|\d+(?:[.,]\d+)?)\s*"
    r"(k|nghìn|ngàn|tr|triệu|đồng|đ)?\b",
    re.IGNORECASE,
)


def log(message: str) -> None:
    print(message, flush=True)


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(value.split())


def parse_amount(number: str, suffix: str) -> float:
    raw = number.strip()
    if "." in raw or "," in raw:
        parts = re.split(r"[.,]", raw)
        if len(parts[-1]) == 3 and len(parts) > 1:
            value = float("".join(parts))
        else:
            value = float(raw.replace(",", "."))
    else:
        value = float(raw)
    suffix = suffix.casefold()
    if suffix in {"k", "nghìn", "ngàn"}:
        value *= 1_000
    elif suffix in {"tr", "triệu"}:
        value *= 1_000_000
    return value


def extract_budget(text: str) -> float | None:
    matches = list(_BUDGET_RE.finditer(text))
    for match in reversed(matches):
        try:
            return parse_amount(match.group(1), match.group(2) or "")
        except ValueError:
            continue
    return None


def parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def read_csv_rows(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def load_conversation_context(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, datetime], int]:
    contexts: dict[str, dict[str, Any]] = {}
    last_train_message_at: dict[str, datetime] = {}
    count = 0
    log("[1/6] Đọc hội thoại và tạo ngữ cảnh khách hàng (không dùng evaluation_truth.csv)...")
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            conversation = json.loads(line)
            conversation_id = str(conversation["conversation_id"])
            customer_id = str(conversation["customer_id"])
            split = conversation["split"]
            customer_messages = []
            pre_recommendation_messages = []
            recommendation_seen = False
            for message in conversation.get("messages", []):
                role = message.get("role")
                content = str(message.get("content") or "")
                if role == "customer" and content:
                    customer_messages.append(content)
                    if not recommendation_seen:
                        pre_recommendation_messages.append(content)
                elif role == "assistant" and is_product_recommendation(content):
                    recommendation_seen = True
            customer_text = " ".join(customer_messages)
            preference_text = " ".join(pre_recommendation_messages) or customer_text
            contexts[conversation_id] = {
                "customer_id": customer_id,
                "split": split,
                "customer_text": customer_text,
                "normalized_text": normalize(customer_text),
                "budget": extract_budget(customer_text),
                "pre_recommendation_text": preference_text,
                "pre_recommendation_normalized_text": normalize(preference_text),
                "pre_recommendation_budget": extract_budget(preference_text),
            }
            if split == TRAIN_SPLIT:
                timestamps = [
                    parsed
                    for message in conversation.get("messages", [])
                    if (parsed := parse_timestamp(message.get("timestamp", ""))) is not None
                ]
                latest = max(timestamps, default=None)
                if latest is not None and latest > last_train_message_at.get(customer_id, datetime.min):
                    last_train_message_at[customer_id] = latest
            count += 1
            if count % PROGRESS_INTERVAL == 0:
                log(f"      Hội thoại: {count:,}")
    log(f"      Hoàn tất {count:,} hội thoại; có mốc thời gian huấn luyện cho {len(last_train_message_at):,} khách.")
    return contexts, last_train_message_at, count


def is_product_recommendation(text: str) -> bool:
    normalized = normalize(text)
    prices = re.findall(r"\b\d{1,3}(?:[.,]\d{3})+\s*(?:đ|đồng)?\b", normalized)
    return len(prices) >= 2 or any(phrase in normalized for phrase in ("ba mẫu", "3 mẫu", "vài mẫu"))


def load_products(path: Path) -> dict[str, dict[str, Any]]:
    products: dict[str, dict[str, Any]] = {}
    for row in read_csv_rows(path):
        product_id = str(row["product_id"])
        products[product_id] = {
            "name": str(row.get("name", "")),
            "normalized_name": normalize(str(row.get("name", ""))),
            "category": str(row.get("category", "")),
            "normalized_category": normalize(str(row.get("category", ""))),
            "color": normalize(str(row.get("color", ""))),
            "price": float(row.get("price") or 0),
            "stock": max(0.0, float(row.get("stock") or 0)),
        }
    return products


def candidate_features(context: dict[str, Any], product: dict[str, Any], position: int) -> list[float]:
    # Only customer input before the assistant's first product list is used.
    # This prevents product-detail questions after the recommendation from
    # revealing the target candidate during offline evaluation.
    text = context["pre_recommendation_normalized_text"]
    budget = context["pre_recommendation_budget"]
    price = product["price"]
    has_budget = budget is not None and budget > 0
    return [
        float(position),
        math.log1p(max(0.0, price)),
        math.log1p(product["stock"]),
        float(product["stock"] > 0),
        float(has_budget),
        float(has_budget and price <= budget),
        float(price / budget) if has_budget else 1.0,
        float(bool(product["color"]) and product["color"] in text),
        float(bool(product["normalized_category"]) and product["normalized_category"] in text),
    ]


def load_interactions(
    path: Path,
    contexts: dict[str, dict[str, Any]],
    products: dict[str, dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray, list[str], list[int], dict[tuple[str, str], list[int]], Counter[str], int]:
    features: list[list[float]] = []
    labels: list[int] = []
    row_splits: list[str] = []
    positions: list[int] = []
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    split_events: Counter[str] = Counter()
    count = 0
    log("[2/6] Ghép 600.000 lượt tương tác với sản phẩm và hội thoại...")
    for row in read_csv_rows(path):
        split = row["split"]
        conversation_id = str(row["conversation_id"])
        product_id = str(row["product_id"])
        if split not in SPLITS:
            raise ValueError(f"Split không hợp lệ: {split}")
        if conversation_id not in contexts:
            raise ValueError(f"Không tìm thấy hội thoại {conversation_id}")
        if product_id not in products:
            raise ValueError(f"Không tìm thấy sản phẩm {product_id}")
        context = contexts[conversation_id]
        if context["split"] != split:
            raise ValueError(f"Split hội thoại/tương tác không khớp: {conversation_id}")
        position = int(row["position"])
        features.append(candidate_features(context, products[product_id], position))
        labels.append(int(row["event"] != "impression"))
        row_splits.append(split)
        positions.append(position)
        groups[(split, conversation_id)].append(count)
        split_events[f"{split}:{row['event']}"] += 1
        count += 1
        if count % INTERACTION_PROGRESS_INTERVAL == 0:
            log(f"      Tương tác: {count:,}")
    log(f"      Hoàn tất {count:,} lượt; {len(groups):,} hội thoại có ghi nhận sản phẩm.")
    return np.asarray(features, dtype=np.float32), np.asarray(labels, dtype=np.int8), row_splits, positions, groups, split_events, count


def ranking_metrics(
    probabilities: np.ndarray,
    labels: np.ndarray,
    row_splits: list[str],
    positions: list[int],
    groups: dict[tuple[str, str], list[int]],
    split: str,
) -> dict[str, float | int]:
    ranks: list[int] = []
    baseline_ranks: list[int] = []
    for (group_split, _), indices in groups.items():
        if group_split != split:
            continue
        if len(indices) != 3 or int(labels[indices].sum()) != 1:
            raise ValueError(f"Mỗi hội thoại cần 3 sản phẩm và đúng 1 mục tiêu: {group_split}")
        target_idx = next(index for index in indices if labels[index] == 1)
        ordered = sorted(indices, key=lambda index: (-float(probabilities[index]), positions[index]))
        ranks.append(ordered.index(target_idx) + 1)
        baseline_ordered = sorted(indices, key=lambda index: positions[index])
        baseline_ranks.append(baseline_ordered.index(target_idx) + 1)
    if not ranks:
        raise ValueError(f"Không có dữ liệu đánh giá cho split {split}")
    total = len(ranks)
    return {
        "conversations": total,
        "hit_at_1": sum(rank == 1 for rank in ranks) / total,
        "hit_at_2": sum(rank <= 2 for rank in ranks) / total,
        "mrr_at_3": sum(1.0 / rank for rank in ranks) / total,
        "position_1_baseline_hit_at_1": sum(rank == 1 for rank in baseline_ranks) / total,
        "position_1_baseline_mrr_at_3": sum(1.0 / rank for rank in baseline_ranks) / total,
    }


def train_rfm(
    dataset_dir: Path,
    output_dir: Path,
    last_train_message_at: dict[str, datetime],
) -> tuple[dict[str, Any], int]:
    log("[5/6] Tạo phân khúc RFM từ đơn hoàn tất thuộc tập train; loại đơn hủy/hoàn...")
    customers = [str(row["customer_id"]) for row in read_csv_rows(dataset_dir / "customers.csv")]
    aggregates: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "monetary": 0.0, "last_order": None})
    eligible_orders = 0
    scanned_orders = 0
    train_completed_orders_scanned = 0
    train_completed_after_cutoff = 0
    train_completed_missing_timestamp_or_cutoff = 0
    for row in read_csv_rows(dataset_dir / "orders.csv"):
        scanned_orders += 1
        if row.get("split") != TRAIN_SPLIT or row.get("status", "").casefold() != "completed":
            continue
        train_completed_orders_scanned += 1
        customer_id = str(row["customer_id"])
        cutoff = last_train_message_at.get(customer_id)
        order_date = parse_timestamp(row.get("created_at", ""))
        if cutoff is None or order_date is None:
            train_completed_missing_timestamp_or_cutoff += 1
            continue
        if order_date > cutoff:
            train_completed_after_cutoff += 1
            continue
        aggregate = aggregates[customer_id]
        aggregate["count"] += 1
        aggregate["monetary"] += float(row.get("total_amount") or 0)
        if aggregate["last_order"] is None or order_date > aggregate["last_order"]:
            aggregate["last_order"] = order_date
        eligible_orders += 1
    if not customers:
        raise ValueError("customers.csv không có khách hàng")

    reference_times = [last_train_message_at[cid] for cid in customers if cid in last_train_message_at]
    if not reference_times:
        raise ValueError("Không có mốc thời gian tập train để tính RFM")
    global_cutoff = max(reference_times)
    raw_rows: list[dict[str, Any]] = []
    scaled_features: list[list[float]] = []
    for customer_id in customers:
        aggregate = aggregates[customer_id]
        order_count = int(aggregate["count"])
        last_order = aggregate["last_order"]
        cutoff = last_train_message_at.get(customer_id, global_cutoff)
        recency_days = max(0, (cutoff - last_order).days) if last_order else 3650
        monetary = float(aggregate["monetary"])
        raw_rows.append({
            "customer_id": customer_id,
            "recency_days": recency_days,
            "frequency_completed_orders": order_count,
            "monetary_completed_orders": round(monetary, 2),
            "has_completed_order": int(order_count > 0),
        })
        scaled_features.append([
            math.log1p(recency_days),
            math.log1p(order_count),
            math.log1p(monetary),
            float(order_count > 0),
        ])

    rfm_pipeline = Pipeline([
        ("scale", StandardScaler()),
        ("cluster", KMeans(n_clusters=4, n_init=10, random_state=20261011)),
    ])
    x_rfm = np.asarray(scaled_features, dtype=np.float32)
    labels = rfm_pipeline.fit_predict(x_rfm)
    cluster_counts = Counter(int(label) for label in labels)
    cluster_summaries: dict[str, Any] = {}
    for cluster_id in sorted(cluster_counts):
        members = [row for row, label in zip(raw_rows, labels) if int(label) == cluster_id]
        cluster_summaries[str(cluster_id)] = {
            "customers": len(members),
            "median_recency_days": float(np.median([row["recency_days"] for row in members])),
            "median_frequency": float(np.median([row["frequency_completed_orders"] for row in members])),
            "median_monetary": float(np.median([row["monetary_completed_orders"] for row in members])),
            "customers_without_completed_orders": sum(not row["has_completed_order"] for row in members),
        }
    assignment_path = output_dir / "rfm_assignments.csv"
    with assignment_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*raw_rows[0].keys(), "cluster_id"])
        writer.writeheader()
        for row, label in zip(raw_rows, labels):
            writer.writerow({**row, "cluster_id": int(label)})
    joblib.dump({
        "pipeline": rfm_pipeline,
        "features": ["log_recency_days", "log_frequency", "log_monetary", "has_completed_order"],
        "random_state": 20261011,
        "n_clusters": 4,
        "training_scope": "train split only; completed orders only; timestamps after each customer's latest train conversation excluded",
    }, output_dir / "rfm_kmeans.joblib")
    result = {
        "customers_segmented": len(customers),
        "orders_scanned": scanned_orders,
        "completed_train_orders_used": eligible_orders,
        "excluded_orders_not_train_completed": scanned_orders - train_completed_orders_scanned,
        "train_completed_orders_after_customer_cutoff_excluded": train_completed_after_cutoff,
        "train_completed_orders_missing_timestamp_or_customer_cutoff_excluded": train_completed_missing_timestamp_or_cutoff,
        "features": ["recency_days", "frequency_completed_orders", "monetary_completed_orders", "has_completed_order"],
        "cluster_ids_are_arbitrary_not_business_labels": True,
        "clusters": cluster_summaries,
    }
    log(f"      Phân nhóm xong {len(customers):,} khách vào 4 cụm; dùng {eligible_orders:,} đơn train đã hoàn tất.")
    return result, eligible_orders


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True, help="Thư mục dataset chứa CSV và conversations.jsonl")
    parser.add_argument("--output-root", type=Path, required=True, help="Thư mục training_runs sẽ được tạo bên trong")
    args = parser.parse_args()
    dataset_dir = args.data_dir.resolve()
    output_root = args.output_root.resolve()
    required = ["conversations.jsonl", "interactions.csv", "products.csv", "customers.csv", "orders.csv"]
    missing = [name for name in required if not (dataset_dir / name).is_file()]
    if missing:
        parser.error("Thiếu dữ liệu: " + ", ".join(missing))
    output_root.mkdir(parents=True, exist_ok=True)
    run_name = datetime.now().strftime("run_%Y%m%d_%H%M%S")
    output_dir = output_root / run_name
    suffix = 1
    while output_dir.exists():
        output_dir = output_root / f"{run_name}_{suffix}"
        suffix += 1
    output_dir.mkdir()
    started = time.perf_counter()
    log("Huấn luyện thử nghiệm cục bộ (CPU) — dữ liệu tổng hợp, không fine-tune chatbot.")
    log(f"Thư mục dữ liệu: {dataset_dir}")
    log(f"Thư mục kết quả: {output_dir}")

    contexts, customer_cutoffs, conversations_read = load_conversation_context(dataset_dir / "conversations.jsonl")
    log("[2a/6] Đọc danh mục sản phẩm...")
    products = load_products(dataset_dir / "products.csv")
    log(f"      Đã đọc {len(products):,} sản phẩm.")
    x, y, row_splits, positions, groups, split_events, interactions_read = load_interactions(
        dataset_dir / "interactions.csv", contexts, products
    )
    train_indices = np.fromiter((i for i, split in enumerate(row_splits) if split == TRAIN_SPLIT), dtype=np.int64)
    if not len(train_indices):
        raise ValueError("Không có lượt train")
    for key, indices in groups.items():
        if len(indices) != 3 or int(y[indices].sum()) != 1:
            raise ValueError(f"Nhóm dữ liệu sai cấu trúc tại hội thoại {key[1]}: cần 3 ứng viên, 1 mục tiêu")

    log(f"[3/6] Huấn luyện bộ xếp hạng Logistic Regression trên {len(train_indices):,} lượt train...")
    ranker = Pipeline([
        ("scale", StandardScaler()),
        ("ranker", LogisticRegression(C=1.0, max_iter=300, solver="lbfgs", random_state=20261011)),
    ])
    ranker.fit(x[train_indices], y[train_indices])
    log("      Hoàn tất huấn luyện bộ xếp hạng.")
    log("[4/6] Đo Hit@1, Hit@2 và MRR@3 trên validation/test (không dùng để fit)...")
    probabilities = ranker.predict_proba(x)[:, 1]
    validation_metrics = ranking_metrics(probabilities, y, row_splits, positions, groups, "validation")
    test_metrics = ranking_metrics(probabilities, y, row_splits, positions, groups, "test")
    log(
        "      Validation: Hit@1={:.3f}, MRR@3={:.3f} | Test: Hit@1={:.3f}, MRR@3={:.3f}".format(
            validation_metrics["hit_at_1"], validation_metrics["mrr_at_3"],
            test_metrics["hit_at_1"], test_metrics["mrr_at_3"],
        )
    )

    rfm_result, _ = train_rfm(dataset_dir, output_dir, customer_cutoffs)
    log("[6/6] Lưu mô hình, phân khúc khách hàng và báo cáo...")
    joblib.dump({
        "pipeline": ranker,
        "features": FEATURE_NAMES,
        "label_definition": "event != impression; predicts the product candidate discussed/selected in the synthetic interaction log, not purchase conversion",
        "training_split": TRAIN_SPLIT,
        "random_state": 20261011,
    }, output_dir / "product_choice_ranker.joblib")
    elapsed = time.perf_counter() - started
    report = {
        "status": "completed",
        "created_at_local": datetime.now().astimezone().isoformat(timespec="seconds"),
        "runtime_seconds": round(elapsed, 2),
        "device": "local CPU",
        "dataset": {
            "path": str(dataset_dir),
            "provenance": "synthetic/offline demo dataset; not real shop data",
            "conversations_read": conversations_read,
            "products_read": len(products),
            "interaction_rows_read": interactions_read,
            "evaluation_truth_opened_or_used": False,
        },
        "product_ranker": {
            "model": "StandardScaler + LogisticRegression",
            "training_rows": int(len(train_indices)),
            "training_positive_rows": int(y[train_indices].sum()),
            "feature_names": FEATURE_NAMES,
            "metrics": {"validation": validation_metrics, "test": test_metrics},
            "interpretation": "Ranking of three displayed synthetic candidates using only customer messages before the assistant's first product recommendation, product, inventory, stated budget/color/category, and position. Product names and later customer messages are excluded to prevent target leakage. These scores are not chatbot accuracy or purchase-conversion rates.",
        },
        "rfm": rfm_result,
        "outputs": [
            "product_choice_ranker.joblib",
            "rfm_kmeans.joblib",
            "rfm_assignments.csv",
            "training_report.json",
        ],
    }
    with (output_dir / "training_report.json").open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    log(f"Hoàn tất trong {elapsed:.1f} giây. Kết quả: {output_dir}")
    log(f"Test Hit@1={test_metrics['hit_at_1']:.3f}; baseline vị trí đầu={test_metrics['position_1_baseline_hit_at_1']:.3f}; Test MRR@3={test_metrics['mrr_at_3']:.3f}.")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log("Đã dừng theo yêu cầu bàn phím.")
        raise SystemExit(130)
