#!/usr/bin/env python3
"""Train offline RFM clusters and a sampled next-basket ranker per industry dataset.

Public dataset IDs and labels are for offline benchmarking only. This does not
install a checkpoint into a live CRM tenant or train a bandit policy.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import joblib
import numpy as np
from sklearn.cluster import MiniBatchKMeans
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import silhouette_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


FEATURES = [
    "log_recency_days",
    "log_frequency",
    "log_monetary",
    "has_monetary",
    "log_item_popularity",
    "log_customer_item_frequency",
    "log_days_since_customer_item_purchase",
]
SEED = 20261101
SUPPORTED = (
    "dunnhumby", "hm", "olist", "retailrocket",
    "online_retail", "online_retail_ii",
)


@dataclass
class Basket:
    user: str
    basket_id: str
    day: float
    items: dict[str, float] = field(default_factory=dict)
    amount: float = 0.0


def find_file(root: Path, name: str) -> Path:
    matches = list(root.rglob(name))
    if not matches:
        raise FileNotFoundError(f"Không tìm thấy {name} trong {root}")
    return min(matches, key=lambda path: (len(path.parts), str(path).lower()))


def day_number(value: str, *, numeric_day: bool = False, milliseconds: bool = False) -> float:
    value = str(value or "").strip()
    if not value:
        raise ValueError("missing event time")
    if numeric_day or milliseconds:
        number = float(value)
        return number / 86_400_000 if milliseconds else number
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.strptime(value[:10], "%Y-%m-%d")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp() / 86_400


def add_line(
    baskets: dict[tuple[str, str], Basket], user: str, basket_id: str,
    item: str, day: float, amount: float, quantity: float = 1.0,
) -> None:
    if not user or not item or not math.isfinite(day):
        return
    key = (user, basket_id or f"{user}:{day}")
    basket = baskets.get(key)
    if basket is None:
        basket = baskets[key] = Basket(user=user, basket_id=key[1], day=day)
    basket.day = min(basket.day, day)
    basket.items[item] = basket.items.get(item, 0.0) + max(quantity, 0.0)
    basket.amount += max(amount, 0.0)


def read_csv(path: Path) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def read_excel(path: Path) -> Iterable[dict[str, Any]]:
    """Stream workbook rows; openpyxl is needed only for Excel sources."""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError(
            "Để đọc bộ Online Retail dạng Excel, hãy cài openpyxl: python -m pip install openpyxl"
        ) from exc

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in workbook.worksheets:
            rows = sheet.iter_rows(values_only=True)
            headers = next(rows, None)
            if not headers:
                continue
            names = [str(value).strip() if value is not None else "" for value in headers]
            if not any(names):
                continue
            for values in rows:
                yield {name: value for name, value in zip(names, values) if name}
    finally:
        workbook.close()


def normalize_identifier(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def load_dataset(
    root: Path, source: str, max_events: int,
) -> tuple[list[Basket], list[str], int, bool, dict[str, Any]]:
    baskets: dict[tuple[str, str], Basket] = {}
    files: list[str] = []
    count = 0
    truncated = False
    cleaning: Counter[str] = Counter()
    min_day: float | None = None
    max_day: float | None = None

    def add(
        user: str, basket: str, item: str, day: float, amount: float,
        quantity: float = 1.0, *, allow_missing_amount: bool = False,
    ) -> bool:
        nonlocal count, truncated, min_day, max_day
        user, basket, item = (str(value or "").strip() for value in (user, basket, item))
        if not user:
            cleaning["excluded_missing_customer_id"] += 1
            return False
        if not basket:
            cleaning["excluded_missing_basket_id"] += 1
            return False
        if not item:
            cleaning["excluded_missing_item_id"] += 1
            return False
        if not math.isfinite(day):
            cleaning["excluded_invalid_event_time"] += 1
            return False
        if not math.isfinite(quantity):
            cleaning["excluded_invalid_quantity"] += 1
            return False
        if quantity <= 0:
            cleaning["excluded_nonpositive_quantity"] += 1
            return False
        if not math.isfinite(amount):
            cleaning["excluded_invalid_amount"] += 1
            return False
        if amount <= 0 and not allow_missing_amount:
            cleaning["excluded_nonpositive_amount"] += 1
            return False
        if max_events and count >= max_events:
            truncated = True
            return False
        key = (user, basket)
        existing = baskets.get(key)
        if existing and item in existing.items:
            cleaning["duplicate_customer_basket_item_rows_aggregated"] += 1
        add_line(baskets, user, basket, item, day, amount, quantity)
        count += 1
        cleaning["rows_accepted"] += 1
        min_day = day if min_day is None else min(min_day, day)
        max_day = day if max_day is None else max(max_day, day)
        return True

    def parse_float(value: Any, *, default: float | None = None) -> float:
        if value in (None, ""):
            if default is not None:
                return default
            raise ValueError("missing numeric value")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite numeric value")
        return number

    if source == "dunnhumby":
        path = find_file(root, "transaction_data.csv")
        files.append(str(path))
        for row in read_csv(path):
            cleaning["rows_seen"] += 1
            try:
                day = day_number(row.get("DAY", ""), numeric_day=True)
                amount = parse_float(row.get("SALES_VALUE"))
                quantity = parse_float(row.get("QUANTITY"))
                add(row.get("household_key", ""), row.get("BASKET_ID", ""), row.get("PRODUCT_ID", ""),
                    day, amount, quantity)
            except (KeyError, ValueError, TypeError, OverflowError):
                cleaning["excluded_invalid_date_or_numeric"] += 1
                continue
            if truncated:
                break
    elif source == "hm":
        path = find_file(root, "transactions_train.csv")
        files.append(str(path))
        for row in read_csv(path):
            cleaning["rows_seen"] += 1
            try:
                user, date = row["customer_id"], row["t_dat"]
                add(user, f"{user}:{date}", row["article_id"], day_number(date),
                    parse_float(row.get("price")))
            except (KeyError, ValueError, TypeError, OverflowError):
                cleaning["excluded_invalid_date_or_numeric"] += 1
                continue
            if truncated:
                break
    elif source in {"online_retail", "online_retail_ii"}:
        filename = "Online Retail.xlsx" if source == "online_retail" else "online_retail_II.xlsx"
        path = find_file(root, filename)
        files.append(str(path))
        for row in read_excel(path):
            cleaning["rows_seen"] += 1
            invoice = normalize_identifier(row.get("Invoice") or row.get("InvoiceNo"))
            user = normalize_identifier(row.get("Customer ID") or row.get("CustomerID"))
            item = normalize_identifier(row.get("StockCode"))
            if invoice.casefold().startswith("c"):
                cleaning["excluded_cancelled_invoice"] += 1
                continue
            if not user:
                cleaning["excluded_missing_customer_id"] += 1
                continue
            if not invoice:
                cleaning["excluded_missing_basket_id"] += 1
                continue
            if not item:
                cleaning["excluded_missing_item_id"] += 1
                continue
            try:
                quantity = parse_float(row.get("Quantity"))
                unit_price = parse_float(row.get("Price") or row.get("UnitPrice"))
                invoice_date = row.get("InvoiceDate")
                day = day_number(str(invoice_date))
                add(user, invoice, item, day, quantity * unit_price, quantity)
            except (KeyError, ValueError, TypeError, OverflowError):
                cleaning["excluded_invalid_date_or_numeric"] += 1
                continue
            if truncated:
                break
    elif source == "retailrocket":
        path = find_file(root, "events.csv")
        files.append(str(path))
        for row in read_csv(path):
            cleaning["rows_seen"] += 1
            if str(row.get("event", "")).casefold() != "transaction":
                cleaning["excluded_non_transaction_event"] += 1
                continue
            try:
                user, stamp = row["visitorid"], row["timestamp"]
                basket = row.get("transactionid") or f"{user}:{stamp}"
                add(user, basket, row["itemid"], day_number(stamp, milliseconds=True), 0.0,
                    allow_missing_amount=True)
            except (KeyError, ValueError, TypeError, OverflowError):
                cleaning["excluded_invalid_date_or_numeric"] += 1
                continue
            if truncated:
                break
    else:
        orders_path = find_file(root, "olist_orders_dataset.csv")
        items_path = find_file(root, "olist_order_items_dataset.csv")
        customers_path = find_file(root, "olist_customers_dataset.csv")
        files.extend(map(str, (orders_path, items_path, customers_path)))
        customer_ids = {
            row["customer_id"]: row.get("customer_unique_id") or row["customer_id"]
            for row in read_csv(customers_path)
            if row.get("customer_id")
        }
        cleaning["support_customer_rows_read"] = sum(1 for _ in read_csv(customers_path))
        orders: dict[str, tuple[str, float]] = {}
        for row in read_csv(orders_path):
            cleaning["support_order_rows_read"] += 1
            if row.get("order_status") != "delivered":
                cleaning["excluded_non_delivered_orders"] += 1
                continue
            try:
                order_id = (row.get("order_id") or "").strip()
                user = customer_ids.get(row.get("customer_id", ""), "")
                if not order_id:
                    cleaning["excluded_order_missing_id"] += 1
                    continue
                if not user:
                    cleaning["excluded_order_missing_customer_mapping"] += 1
                    continue
                orders[row["order_id"]] = (
                    user,
                    day_number(row["order_purchase_timestamp"]),
                )
            except (KeyError, ValueError, TypeError, OverflowError):
                cleaning["excluded_invalid_order_date"] += 1
                continue
        for row in read_csv(items_path):
            cleaning["rows_seen"] += 1
            order = orders.get(row.get("order_id", ""))
            if not order:
                cleaning["excluded_item_not_in_delivered_order"] += 1
                continue
            try:
                # Monetary is merchandise spend; freight is excluded consistently
                # with the dataset's documented RFM definition.
                add(order[0], row.get("order_id", ""), row.get("product_id", ""), order[1],
                    parse_float(row.get("price")))
            except (KeyError, ValueError, TypeError, OverflowError):
                cleaning["excluded_invalid_item_amount"] += 1
                continue
            if truncated:
                break

    cleaning["rows_accepted"] = count
    cleaning["unique_customers"] = len({basket.user for basket in baskets.values()})
    cleaning["unique_baskets"] = len(baskets)
    cleaning["unique_products"] = len({item for basket in baskets.values() for item in basket.items})
    cleaning["event_date_min_day"] = min_day
    cleaning["event_date_max_day"] = max_day
    cleaning["cleaning_rules"] = {
        "tenant_or_source_customer_ids_are_not_merged": True,
        "grouping": "customer + source basket/order; H&M basket is customer + purchase date",
        "monetary": "source transaction amount; Olist uses merchandise price and excludes freight; Retailrocket has no monetary field",
        "refunds_cancellations": "cancelled/return/nonpositive rows excluded when identifiable in source",
    }
    return list(baskets.values()), files, count, truncated, dict(cleaning)


def rfm_profiles(
    baskets: list[Basket], monetary_available: bool,
) -> tuple[list[dict[str, Any]], Any, dict[str, Any]]:
    by_user: dict[str, list[Basket]] = defaultdict(list)
    for basket in baskets:
        by_user[basket.user].append(basket)
    as_of = max((basket.day for basket in baskets), default=0.0)
    rows = []
    features = ["recency_days", "frequency", "monetary"] if monetary_available else ["recency_days", "frequency"]
    matrix = []
    for user, purchases in by_user.items():
        latest = max(basket.day for basket in purchases)
        recency = max(0.0, as_of - latest)
        frequency = len(purchases)
        monetary = sum(basket.amount for basket in purchases)
        values = {"recency_days": recency, "frequency": frequency, "monetary": monetary}
        matrix.append([math.log1p(max(0.0, values[name])) for name in features])
        rows.append({"customer_id": user, **values})
    if len(rows) < 2:
        return rows, None, {"status": "not_enough_customers_for_clustering"}
    scaled = StandardScaler()
    x = scaled.fit_transform(np.asarray(matrix, dtype=float))
    clusters = min(4, len(rows))
    model = MiniBatchKMeans(
        n_clusters=clusters, random_state=SEED, batch_size=min(1024, max(32, len(rows))),
        n_init=3,
    )
    labels = model.fit_predict(x)
    for row, label in zip(rows, labels):
        row["cluster_id"] = int(label)
    cluster_sizes = dict(Counter(str(int(label)) for label in labels))
    sample_size = min(5000, len(rows))
    quality = {
        "cluster_sizes": cluster_sizes,
        "silhouette_sample_size": sample_size,
        "silhouette_score": round(float(silhouette_score(
            x, labels, sample_size=sample_size, random_state=SEED,
        )), 6) if len(cluster_sizes) > 1 else None,
    }
    return rows, {"features": features, "scaler": scaled, "model": model, "as_of_day": as_of}, quality


def candidate_features(
    user: str, item: str, target_day: float,
    user_baskets: Counter[str], user_spend: Counter[str], user_last: dict[str, float],
    user_item_count: dict[str, Counter[str]], user_item_last: dict[str, dict[str, float]],
    item_count: Counter[str], monetary_available: bool,
) -> list[float]:
    last_day = user_last.get(user, target_day - 365)
    last_item_day = user_item_last.get(user, {}).get(item, target_day - 3650)
    return [
        math.log1p(max(0.0, target_day - last_day)),
        math.log1p(user_baskets[user]),
        math.log1p(max(0.0, user_spend[user])),
        float(monetary_available),
        math.log1p(item_count[item]),
        math.log1p(user_item_count.get(user, Counter())[item]),
        math.log1p(max(0.0, target_day - last_item_day)),
    ]


def ranking_metrics(groups: list[dict[str, Any]], *, k: int = 5) -> dict[str, float | int]:
    precision = recall = ndcg = 0.0
    if not groups:
        return {"groups": 0, "precision_at_5": 0.0, "recall_at_5": 0.0, "ndcg_at_5": 0.0}
    for group in groups:
        ranked = sorted(zip(group["scores"], group["labels"]), reverse=True)[:k]
        hits = sum(label for _, label in ranked)
        positives = sum(group["labels"])
        precision += hits / max(1, min(k, len(group["labels"])))
        recall += hits / max(1, positives)
        dcg = sum(label / math.log2(index + 2) for index, (_, label) in enumerate(ranked))
        ideal = sum(1 / math.log2(index + 2) for index in range(min(k, positives)))
        ndcg += dcg / max(ideal, 1e-12)
    n = len(groups)
    return {"groups": n, "precision_at_5": round(precision / n, 6),
            "recall_at_5": round(recall / n, 6), "ndcg_at_5": round(ndcg / n, 6)}


def train_ranker(
    baskets: list[Basket], negative_samples: int, monetary_available: bool,
) -> tuple[Any, dict[str, Any]]:
    by_user: dict[str, list[Basket]] = defaultdict(list)
    for basket in baskets:
        by_user[basket.user].append(basket)
    ordered = sorted(baskets, key=lambda basket: basket.day)
    days = sorted({basket.day for basket in ordered})
    catalog = sorted({item for basket in baskets for item in basket.items})
    empty_report = {"status": "not_enough_temporal_history", "training_customers": 0,
                    "test_customers": 0, "metrics": {}, "evaluation": "sampled next-basket proxy"}
    if len(days) < 4 or len(catalog) < 3:
        return None, empty_report
    cutoff = days[min(len(days) - 1, int(len(days) * 0.8))]
    targets: dict[tuple[str, str], str] = {}
    train_count = test_count = 0
    for user, purchases in by_user.items():
        purchases.sort(key=lambda basket: (basket.day, basket.basket_id))
        history = [basket for basket in purchases if basket.day < cutoff]
        future = [basket for basket in purchases if basket.day >= cutoff]
        if len(history) < 2 or not future:
            continue
        targets[(user, history[-1].basket_id)] = "train"
        targets[(user, future[0].basket_id)] = "test"
        train_count += 1
        test_count += 1
    if not train_count or not test_count:
        return None, empty_report

    user_baskets: Counter[str] = Counter()
    user_spend: Counter[str] = Counter()
    user_last: dict[str, float] = {}
    user_item_count: dict[str, Counter[str]] = defaultdict(Counter)
    user_item_last: dict[str, dict[str, float]] = defaultdict(dict)
    item_count: Counter[str] = Counter()
    rng = random.Random(SEED)
    train_x: list[list[float]] = []
    train_y: list[int] = []
    test_groups: list[dict[str, Any]] = []
    by_day: dict[float, list[Basket]] = defaultdict(list)
    for basket in ordered:
        by_day[basket.day].append(basket)

    for day in sorted(by_day):
        todays = by_day[day]
        for basket in todays:
            split = targets.get((basket.user, basket.basket_id))
            if not split:
                continue
            positives = set(basket.items)
            if not positives:
                continue
            negatives: set[str] = set()
            attempts = 0
            target_negatives = min(negative_samples, max(0, len(catalog) - len(positives)))
            while len(negatives) < target_negatives and attempts < target_negatives * 20 + 20:
                candidate = catalog[rng.randrange(len(catalog))]
                if candidate not in positives:
                    negatives.add(candidate)
                attempts += 1
            candidates = [(item, 1) for item in sorted(positives)]
            candidates.extend((item, 0) for item in sorted(negatives))
            vectors = [candidate_features(
                basket.user, item, day, user_baskets, user_spend, user_last,
                user_item_count, user_item_last, item_count, monetary_available,
            ) for item, _ in candidates]
            labels = [label for _, label in candidates]
            if split == "train":
                train_x.extend(vectors)
                train_y.extend(labels)
            else:
                test_groups.append({"vectors": vectors, "labels": labels})

        # Process same-day purchases together so a target never sees another
        # purchase from its own timestamp in popularity or RFM features.
        for basket in todays:
            user_baskets[basket.user] += 1
            user_spend[basket.user] += basket.amount
            user_last[basket.user] = day
            for item, quantity in basket.items.items():
                user_item_count[basket.user][item] += quantity
                user_item_last[basket.user][item] = day
                item_count[item] += quantity

    if not train_x or len(set(train_y)) < 2 or not test_groups:
        return None, empty_report
    model = make_pipeline(
        StandardScaler(),
        LogisticRegression(max_iter=300, class_weight="balanced", random_state=SEED),
    )
    model.fit(np.asarray(train_x, dtype=np.float64), np.asarray(train_y, dtype=np.int8))
    for group in test_groups:
        group["scores"] = model.predict_proba(np.asarray(group.pop("vectors"), dtype=np.float64))[:, 1].tolist()
    return model, {
        "status": "trained_offline",
        "algorithm": "StandardScaler + LogisticRegression",
        "features": FEATURES,
        "training_customers": train_count,
        "test_customers": test_count,
        "training_rows": len(train_y),
        "negative_samples_per_target": negative_samples,
        "metrics": ranking_metrics(test_groups),
        "evaluation": "time split; each positive target basket is ranked against sampled unobserved catalog items; not an impression-based conversion estimate",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=SUPPORTED)
    parser.add_argument("--data-root", type=Path, default=Path(r"D:\CRM_Industry_Datasets"))
    parser.add_argument("--output-root", type=Path, help="Defaults to <data-root>/trained_models")
    parser.add_argument("--max-events", type=int, default=500_000,
                        help="Maximum purchase rows to read (0 reads all; default 500000)")
    parser.add_argument("--negative-samples", type=int, default=10)
    args = parser.parse_args()
    if args.max_events < 0 or args.negative_samples < 1:
        parser.error("--max-events phải >= 0 và --negative-samples phải >= 1")
    run_started_at = datetime.now(timezone.utc)
    started_clock = time.perf_counter()
    root = args.data_root.resolve()
    output_root = (args.output_root or root / "trained_models").resolve()
    print(f"[{run_started_at.isoformat()}] source={args.source} root={root}", flush=True)
    baskets, source_files, events_read, truncated, cleaning = load_dataset(root, args.source, args.max_events)
    if not baskets:
        raise SystemExit("Không tìm thấy giao dịch hợp lệ để train.")
    baskets.sort(key=lambda basket: (basket.day, basket.user, basket.basket_id))
    monetary_available = args.source != "retailrocket"
    profiles, rfm_model, rfm_quality = rfm_profiles(baskets, monetary_available)
    ranker, rank_report = train_ranker(baskets, args.negative_samples, monetary_available)

    run_dir = output_root / args.source / datetime.now().strftime("run_%Y%m%d_%H%M%S")
    suffix = 1
    base_dir = run_dir
    while run_dir.exists():
        run_dir = base_dir.with_name(f"{base_dir.name}_{suffix}")
        suffix += 1
    run_dir.mkdir(parents=True)
    with (run_dir / "rfm_profiles.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["customer_id", "recency_days", "frequency", "monetary", "cluster_id"]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(profiles)
    if rfm_model is not None:
        joblib.dump(rfm_model, run_dir / "rfm_segmenter.joblib")
    if ranker is not None:
        joblib.dump({"pipeline": ranker, "features": FEATURES, "source": args.source,
                     "label": "next_basket_purchase_vs_sampled_unobserved_item", "random_state": SEED},
                    run_dir / "next_basket_ranker.joblib")

    finished_at = datetime.now(timezone.utc)
    duration_seconds = round(time.perf_counter() - started_clock, 3)
    file_info = []
    for raw_path in source_files:
        path = Path(raw_path)
        stat = path.stat()
        file_info.append({
            "path": str(path),
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        })
    cleaning_log = {
        "source": args.source,
        "started_at_utc": run_started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "duration_seconds": duration_seconds,
        "command": [sys.executable, *sys.argv],
        "source_files": file_info,
        "counts": cleaning,
        "truncated": truncated,
    }
    (run_dir / "data_cleaning_log.json").write_text(
        json.dumps(cleaning_log, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = {
        "source": args.source,
        "source_files": source_files,
        "events_read": events_read,
        "event_limit_reached": truncated,
        "started_at_utc": run_started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "duration_seconds": duration_seconds,
        "command": [sys.executable, *sys.argv],
        "cleaning_log_file": "data_cleaning_log.json",
        "data_cleaning": cleaning,
        "baskets": len(baskets),
        "customers": len(profiles),
        "products": len({item for basket in baskets for item in basket.items}),
        "monetary_available": monetary_available,
        "rfm_training_decision": (
            "offline_rfm_candidate; fit and validate per tenant on consented shop data before any production use"
            if monetary_available else
            "rf_only; excluded from complete RFM because monetary data is unavailable"
        ),
        "rfm": {"algorithm": "log1p + StandardScaler + MiniBatchKMeans",
                "features": ["recency_days", "frequency", "monetary"] if monetary_available else ["recency_days", "frequency"],
                "clusters": min(4, len(profiles)), "profiles_file": "rfm_profiles.csv",
                "quality": rfm_quality},
        "supervised_ranker": rank_report,
        "reinforcement_learning": {
            "status": "not_trained",
            "reason": "Public transaction datasets lack recommendation impressions, chosen actions, and propensities; train LinUCB only from real CRM exposure and feedback logs.",
        },
        "rag": {
            "status": "offline_candidate_signal_only",
            "reason": "These sources have no customer query or displayed RAG candidates, so the ranker does not learn semantic relevance, BM25, RRF, or PPR weights.",
        },
        "production_ready": False,
        "note": "Public user/product identifiers are dataset-local. Do not load this artifact into a live tenant.",
    }
    (run_dir / "training_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    result = {"output": str(run_dir), "events": events_read, "baskets": len(baskets),
              "customers": len(profiles), "cleaning": cleaning,
              "rfm_quality": rfm_quality, "ranker": rank_report["status"],
              "metrics": rank_report.get("metrics", {}),
              "duration_seconds": duration_seconds}
    (run_dir / "run.log").write_text(
        f"command: {sys.executable} {' '.join(sys.argv)}\n"
        f"started_at_utc: {run_started_at.isoformat()}\n"
        f"finished_at_utc: {finished_at.isoformat()}\n"
        f"duration_seconds: {duration_seconds}\n"
        f"result: {json.dumps(result, ensure_ascii=False)}\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
