#!/usr/bin/env python3
"""Fit a full-data H&M RFM segmenter without loading transaction baskets in RAM.

The H&M archive includes a large image collection. Only transactions_train.csv
is read here; images are irrelevant to Recency, Frequency, and Monetary value.
The output is an offline, dataset-local artifact and is not a tenant model.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
import sys
import time

import joblib
import numpy as np
from sklearn.cluster import MiniBatchKMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler


SEED = 20261103
FEATURES = ("recency_days", "frequency", "monetary")


def train(source: Path, output_root: Path) -> Path:
    started_at = datetime.now(timezone.utc)
    started_clock = time.perf_counter()
    customer_state: dict[str, list[float | int]] = {}
    customers_in_day: set[str] = set()
    current_day_text: str | None = None
    current_day_ordinal: int | None = None
    min_day: int | None = None
    max_day: int | None = None
    baskets = 0
    events_read = 0
    rows_seen = 0
    excluded = {
        "missing_customer_id": 0,
        "missing_event_time": 0,
        "invalid_event_time_or_order": 0,
        "invalid_price": 0,
        "nonpositive_price": 0,
    }

    def finish_day() -> None:
        nonlocal baskets
        if current_day_ordinal is None:
            return
        for customer_id in customers_in_day:
            customer_state[customer_id][2] += 1
        baskets += len(customers_in_day)
        customers_in_day.clear()

    with source.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"customer_id", "t_dat", "price"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"H&M CSV thiếu cột bắt buộc: {sorted(required)}")

        for row in reader:
            rows_seen += 1
            customer_id = (row.get("customer_id") or "").strip()
            day_text = (row.get("t_dat") or "").strip()
            if not customer_id:
                excluded["missing_customer_id"] += 1
                continue
            if not day_text:
                excluded["missing_event_time"] += 1
                continue
            try:
                price = float(row.get("price") or 0)
            except (TypeError, ValueError):
                excluded["invalid_price"] += 1
                continue
            if not math.isfinite(price):
                excluded["invalid_price"] += 1
                continue
            if price <= 0:
                excluded["nonpositive_price"] += 1
                continue
            try:
                if current_day_text is None or day_text != current_day_text:
                    if current_day_text is not None and day_text < current_day_text:
                        raise ValueError(
                            "transactions_train.csv không sắp xếp tăng dần theo t_dat; "
                            "không thể đếm chính xác frequency theo ngày bằng chế độ streaming."
                        )
                    next_ordinal = date.fromisoformat(day_text).toordinal()
                    finish_day()
                    current_day_text = day_text
                    current_day_ordinal = next_ordinal
                    min_day = current_day_ordinal if min_day is None else min(min_day, current_day_ordinal)
                    max_day = current_day_ordinal if max_day is None else max(max_day, current_day_ordinal)
            except ValueError as exc:
                if "không sắp xếp tăng dần" in str(exc):
                    raise
                excluded["invalid_event_time_or_order"] += 1
                continue
            state = customer_state.get(customer_id)
            if state is None:
                customer_state[customer_id] = [current_day_ordinal, price, 0]
            else:
                state[0] = max(int(state[0]), int(current_day_ordinal))
                state[1] = float(state[1]) + price
            customers_in_day.add(customer_id)
            events_read += 1
            if events_read and events_read % 5_000_000 == 0:
                print(f"Read {events_read:,} purchase rows; {len(customer_state):,} customers", flush=True)
        finish_day()

    if not customer_state or min_day is None or max_day is None:
        raise ValueError("Không tìm thấy giao dịch H&M hợp lệ để tính RFM.")

    as_of = max_day
    records: list[dict[str, float | int | str]] = []
    matrix = np.empty((len(customer_state), len(FEATURES)), dtype=np.float64)
    for index, (customer_id, state) in enumerate(customer_state.items()):
        recency = max(0, as_of - int(state[0]))
        frequency = int(state[2])
        monetary = float(state[1])
        records.append({
            "customer_id": customer_id,
            "recency_days": recency,
            "frequency": frequency,
            "monetary": monetary,
        })
        matrix[index] = (math.log1p(recency), math.log1p(frequency), math.log1p(monetary))

    scaler = StandardScaler()
    scaled = scaler.fit_transform(matrix)
    cluster_count = min(4, len(records))
    segmenter = MiniBatchKMeans(
        n_clusters=cluster_count,
        random_state=SEED,
        batch_size=min(1024, max(32, len(records))),
        n_init=3,
    )
    labels = segmenter.fit_predict(scaled)
    cluster_sizes: dict[str, int] = {}
    for record, label in zip(records, labels):
        record["cluster_id"] = int(label)
        key = str(int(label))
        cluster_sizes[key] = cluster_sizes.get(key, 0) + 1
    silhouette_sample_size = min(5000, len(records))
    silhouette = (
        round(float(silhouette_score(
            scaled, labels, sample_size=silhouette_sample_size, random_state=SEED,
        )), 6)
        if len(cluster_sizes) > 1 else None
    )

    now = datetime.now().strftime("run_%Y%m%d_%H%M%S_full_rfm")
    output = output_root / "hm" / now
    suffix = 1
    while output.exists():
        output = output_root / "hm" / f"{now}_{suffix}"
        suffix += 1
    output.mkdir(parents=True)

    profile_path = output / "rfm_profiles.csv"
    with profile_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("customer_id", "recency_days", "frequency", "monetary", "cluster_id"),
        )
        writer.writeheader()
        writer.writerows(records)

    as_of_day = datetime.fromordinal(as_of).replace(tzinfo=timezone.utc).timestamp() / 86_400
    joblib.dump({
        "features": list(FEATURES),
        "scaler": scaler,
        "model": segmenter,
        "as_of_day": as_of_day,
        "source": "hm",
        "source_scope": "offline_full_transaction_file",
    }, output / "rfm_segmenter.joblib")

    finished_at = datetime.now(timezone.utc)
    duration_seconds = round(time.perf_counter() - started_clock, 3)
    source_stat = source.stat()
    cleaning = {
        "rows_seen": rows_seen,
        "rows_accepted": events_read,
        "rows_excluded": sum(excluded.values()),
        "excluded_by_reason": excluded,
        "duplicates_aggregated": 0,
        "frequency_definition": "one purchase basket per distinct customer_id + t_dat",
        "monetary_definition": "sum of positive source price values; source-native normalized values",
    }
    (output / "data_cleaning_log.json").write_text(json.dumps({
        "source": "hm",
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "duration_seconds": duration_seconds,
        "command": [sys.executable, *sys.argv],
        "input_file": {
            "path": str(source), "size_bytes": source_stat.st_size,
            "modified_at": datetime.fromtimestamp(source_stat.st_mtime, timezone.utc).isoformat(),
        },
        "counts": cleaning,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "source": "hm",
        "source_files": [str(source)],
        "events_read": events_read,
        "rows_seen": rows_seen,
        "invalid_rows_skipped": sum(excluded.values()),
        "event_limit_reached": False,
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "duration_seconds": duration_seconds,
        "command": [sys.executable, *sys.argv],
        "data_cleaning": cleaning,
        "cleaning_log_file": "data_cleaning_log.json",
        "baskets": baskets,
        "customers": len(records),
        "monetary_available": True,
        "rfm": {
            "status": "trained_full_dataset",
            "algorithm": "log1p + StandardScaler + MiniBatchKMeans",
            "features": list(FEATURES),
            "clusters": cluster_count,
            "cluster_sizes": cluster_sizes,
            "cluster_quality": {
                "silhouette_score_sampled": silhouette,
                "silhouette_sample_size": silhouette_sample_size,
            },
            "frequency_unit": "distinct customer purchase dates",
            "date_range": {
                "from": date.fromordinal(min_day).isoformat(),
                "to": date.fromordinal(max_day).isoformat(),
            },
            "profiles_file": "rfm_profiles.csv",
        },
        "next_basket_ranker": {
            "status": "not_trained",
            "reason": "This memory-bounded run trains full-data RFM only; use the separate capped industry ranker run for next-basket experiments.",
        },
        "production_ready": False,
        "note": "Public dataset IDs and currency are dataset-local. Do not load this artifact into a live tenant or compare monetary values across sources.",
    }
    (output / "training_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "run.log").write_text(
        f"command: {sys.executable} {' '.join(sys.argv)}\n"
        f"started_at_utc: {started_at.isoformat()}\n"
        f"finished_at_utc: {finished_at.isoformat()}\n"
        f"duration_seconds: {duration_seconds}\n"
        f"rows_seen: {rows_seen}\nrows_accepted: {events_read}\n"
        f"rows_excluded: {sum(excluded.values())}\n"
        f"output: {output}\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(output),
        "rows_seen": rows_seen,
        "events": events_read,
        "excluded_by_reason": excluded,
        "baskets": baskets,
        "customers": len(records),
        "clusters": cluster_sizes,
        "silhouette_score_sampled": silhouette,
        "date_range": report["rfm"]["date_range"],
        "duration_seconds": duration_seconds,
    }, ensure_ascii=False, indent=2), flush=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root", type=Path, default=Path(r"D:\CRM_Industry_Datasets")
    )
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    source = args.data_root.resolve() / "archive" / "transactions_train.csv"
    output_root = (args.output_root or args.data_root.resolve() / "trained_models").resolve()
    if not source.is_file():
        raise SystemExit(f"Không tìm thấy giao dịch H&M: {source}")
    train(source, output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
