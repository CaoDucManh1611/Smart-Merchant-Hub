#!/usr/bin/env python3
"""Inventory, clean, train, and log every RFM-eligible dataset on drive D."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DATASET_DECISIONS = {
    "archive": ("hm", "train_full_rfm", "Customer ID + purchase date + positive price; image files are excluded"),
    "dunnhumby_The-Complete-Journey": ("dunnhumby", "train_full_rfm", "household + basket + product + date + sales value"),
    "olist": ("olist", "train_full_rfm", "delivered orders + customer mapping + order date + merchandise price"),
    "online+retail": ("online_retail", "train_full_rfm", "customer + invoice + date + quantity + unit price"),
    "online+retail+ii": ("online_retail_ii", "train_full_rfm", "customer + invoice + date + quantity + unit price"),
    "Retailrocket": ("retailrocket", "train_rf_only", "customer + transaction event + time; no monetary value"),
    "bank+marketing": (None, "exclude_from_rfm", "campaign contact/response data; not customer purchase orders"),
    "expedia-hotel-recommendations": (None, "exclude_from_rfm", "search/booking data has no transaction monetary value"),
    "online+shoppers+purchasing+intention+dataset": (None, "exclude_from_rfm", "session intention data lacks stable customer purchase history and spend"),
    "wholesale+customers": (None, "exclude_from_rfm", "annual spend summaries have monetary totals but no purchase event dates/frequency"),
    "Yelp-JSON": (None, "exclude_from_rfm", "reviews/tips/check-ins are not transactions and have no purchase monetary value"),
    "DwnlData": (None, "empty_folder", "no usable dataset files found"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def inventory_dataset(path: Path) -> dict[str, Any]:
    files = [item for item in path.rglob("*") if item.is_file()]
    extensions = Counter(item.suffix.lower() or "[none]" for item in files)
    image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
    archives = [str(item) for item in files if item.suffix.lower() in {".zip", ".rar", ".7z"}]
    return {
        "dataset": path.name,
        "path": str(path),
        "files": len(files),
        "size_bytes": sum(item.stat().st_size for item in files),
        "extensions": dict(extensions),
        "image_files": sum(1 for item in files if item.suffix.lower() in image_extensions),
        "archive_files": archives,
    }


def csv_header(stream) -> list[str]:
    line = stream.readline()
    if isinstance(line, bytes):
        line = line.decode("utf-8-sig", errors="replace")
    return next(csv.reader([line])) if line else []


def schema_evidence(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                return {"file": str(path), "format": "csv", "columns": next(csv.reader(stream), [])}
        if suffix == ".json":
            with path.open("r", encoding="utf-8") as stream:
                first = json.loads(stream.readline())
            return {"file": str(path), "format": "jsonl_or_json", "sample_keys": sorted(first) if isinstance(first, dict) else []}
        if suffix == ".xlsx":
            try:
                from openpyxl import load_workbook
            except ImportError:
                return {"file": str(path), "format": "xlsx", "schema_status": "openpyxl_not_available"}
            workbook = load_workbook(path, read_only=True, data_only=True)
            try:
                sheets = []
                for sheet in workbook.worksheets:
                    headers = next(sheet.iter_rows(min_row=1, max_row=1, values_only=True), ())
                    sheets.append({"sheet": sheet.title, "columns": [str(value) for value in headers if value is not None]})
                return {"file": str(path), "format": "xlsx", "sheets": sheets}
            finally:
                workbook.close()
        if suffix == ".zip":
            with zipfile.ZipFile(path) as archive:
                members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
                headers = {}
                for name in members[:3]:
                    with archive.open(name) as stream:
                        headers[name] = csv_header(stream)
                return {"file": str(path), "format": "zip", "csv_members": members, "sample_columns": headers}
    except Exception as exc:  # retain audit findings even if one source file is malformed
        return {"file": str(path), "format": suffix, "schema_error": f"{type(exc).__name__}: {exc}"}
    return {"file": str(path), "format": suffix, "schema_status": "not_parsed"}


def top_level_archives(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in root.iterdir():
        if not path.is_file() or path.suffix.lower() not in {".zip", ".rar", ".7z"}:
            continue
        extracted = root / path.stem
        rows.append({
            "file": str(path),
            "size_bytes": path.stat().st_size,
            "matching_extracted_directory": str(extracted) if extracted.is_dir() else "",
            "decision": "archive_duplicate_not_reprocessed" if extracted.is_dir() else "archive_kept_as_source_candidate",
        })
    return rows


def find_schema_files(root: Path, folder: str) -> list[Path]:
    dataset_root = root / folder
    if not dataset_root.exists():
        return []
    candidates = [p for p in dataset_root.rglob("*") if p.is_file() and p.suffix.lower() in {".csv", ".xlsx", ".json", ".zip"}]
    preferred = {
        "archive": {"transactions_train.csv"},
        "dunnhumby_The-Complete-Journey": {"transaction_data.csv"},
        "olist": {"olist_orders_dataset.csv", "olist_order_items_dataset.csv", "olist_customers_dataset.csv"},
        "online+retail": {"Online Retail.xlsx"},
        "online+retail+ii": {"online_retail_II.xlsx"},
        "Retailrocket": {"events.csv"},
        "bank+marketing": {"bank.zip", "bank-additional.zip"},
        "expedia-hotel-recommendations": {"train.csv"},
        "online+shoppers+purchasing+intention+dataset": {"online_shoppers_intention.csv"},
        "wholesale+customers": {"Wholesale customers data.csv"},
        "Yelp-JSON": {"yelp_academic_dataset_review.json", "yelp_academic_dataset_user.json", "yelp_academic_dataset_business.json", "yelp_academic_dataset_tip.json", "yelp_academic_dataset_checkin.json"},
    }.get(folder, set())
    if preferred:
        selected = [p for p in candidates if p.name in preferred]
        if selected:
            return selected
    return candidates[:10]


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_markdown_report(run_root: Path, summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    """Write a concise human-readable report alongside machine-readable logs."""
    lines = [
        "# RFM dataset training audit",
        "",
        f"- Data root: `{summary['data_root']}`",
        f"- Started (UTC): `{summary['started_at_utc']}`",
        f"- Finished (UTC): `{summary['finished_at_utc']}`",
        f"- Duration: `{summary['duration_seconds']}` seconds",
        "- Scope: offline public-data benchmarks; no public customer IDs or artifacts are loaded into live shops.",
        "",
        "## Dataset inventory and decision",
        "",
        "| Dataset | Files | Size (GiB) | Images | Decision | Reason |",
        "|---|---:|---:|---:|---|---|",
    ]
    for decision in summary["eligibility_decisions"]:
        size_gib = int(decision.get("size_bytes", 0)) / (1024 ** 3)
        lines.append(
            f"| {decision['dataset']} | {decision.get('files', 0)} | {size_gib:.2f} | "
            f"{decision.get('image_files_not_used_for_rfm', 0)} | {decision['decision']} | {decision['reason']} |"
        )
    lines.extend([
        "",
        "Top-level archives with an extracted directory were inventoried but not processed again. The H&M `archive` directory is about 32.19 GiB and contains 105,100 product images; RFM used `transactions_train.csv`, not the images.",
        "",
        "## Training results",
        "",
        "| Source | Status | Rows seen | Rows accepted | Customers | Baskets | Monetary | Clusters | Silhouette (sampled) | Next-basket NDCG@5 |",
        "|---|---|---:|---:|---:|---:|---|---:|---:|---:|",
    ])
    for result in results:
        lines.append(
            f"| {result.get('source', '')} | {result.get('status', '')} | {result.get('rows_seen', '')} | "
            f"{result.get('rows_accepted', '')} | {result.get('customers', '')} | {result.get('baskets', '')} | "
            f"{result.get('monetary_available', '')} | {result.get('rfm_clusters', '')} | "
            f"{result.get('silhouette_score_sampled', '')} | {result.get('next_basket_ndcg_at_5', '')} |"
        )
    lines.extend([
        "",
        "## How to interpret these scores",
        "",
        "- Silhouette describes separation of the fitted RFM clusters; it does not prove that campaign outcomes or customer value improved.",
        "- Next-basket NDCG@5 is a time-split offline benchmark against sampled unobserved products. Different sources have different catalogs and holdouts, so compare only within the same source and protocol.",
        "- Retailrocket has no monetary transaction value. It is RF/behavior-only and is not a complete RFM source.",
        "- H&M was processed in full for RFM only; no next-basket ranker was trained in its memory-bounded run.",
        "- The RFM segmenters must be refit with each shop's own consented transactions, currency, catalog and business-specific time window before serving. Public model files are not production-ready.",
        "- These datasets do not contain RAG query/impression/feedback logs, so they cannot train RAG retrieval weights or a contextual bandit.",
        "",
        "## Audit files",
        "",
        "- `dataset_inventory.csv`, `archive_inventory.csv`, `source_decisions.csv`, `schema_evidence.json`",
        "- `training_results.csv`, `suite_summary.json`, `run.log`, and `logs/<source>.log`",
        "- Each model run contains `data_cleaning_log.json`, `training_report.json`, `run.log`, RFM profiles and fitted artifacts.",
        "",
    ])
    (run_root / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def run_one(source: str, command: list[str], log_path: Path, run_root: Path) -> dict[str, Any]:
    started_at = utc_now()
    started = time.perf_counter()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8", newline="") as log:
        log.write(f"started_at_utc: {started_at}\ncommand: {json.dumps(command, ensure_ascii=False)}\n\n")
        process = subprocess.Popen(
            command,
            cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(f"[{source}] {line}", end="", flush=True)
            log.write(line)
            log.flush()
        code = process.wait()
        finished_at = utc_now()
        duration = round(time.perf_counter() - started, 3)
        log.write(f"\nexit_code: {code}\nfinished_at_utc: {finished_at}\nduration_seconds: {duration}\n")
    latest_report = None
    source_dir = run_root / "models" / source
    if source_dir.exists():
        reports = sorted(source_dir.glob("run_*/training_report.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if reports:
            latest_report = json.loads(reports[0].read_text(encoding="utf-8"))
    return {
        "source": source,
        "status": "completed" if code == 0 and latest_report else "failed",
        "exit_code": code,
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "duration_seconds": duration,
        "report_path": str(reports[0]) if source_dir.exists() and reports else "",
        "output_path": str(reports[0].parent) if source_dir.exists() and reports else "",
        "report": latest_report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path(r"D:\CRM_Industry_Datasets"))
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    root = args.data_root.resolve()
    output_root = (args.output_root or root / "training_audit_runs").resolve()
    run_root = output_root / datetime.now().strftime("run_%Y%m%d_%H%M%S")
    run_root.mkdir(parents=True, exist_ok=False)
    (run_root / "logs").mkdir()

    suite_started = utc_now()
    suite_clock = time.perf_counter()
    inventory = []
    decisions = []
    schema_rows = []
    for folder, (source, decision, reason) in DATASET_DECISIONS.items():
        path = root / folder
        if path.exists():
            item = inventory_dataset(path)
            inventory.append(item)
            if not source and decision not in {"empty_folder"}:
                for schema_path in find_schema_files(root, folder):
                    schema_rows.append(schema_evidence(schema_path))
            decisions.append({
                "dataset": folder,
                "path": str(path),
                "decision": decision,
                "training_source": source or "",
                "reason": reason,
                "files": item["files"],
                "size_bytes": item["size_bytes"],
                "image_files_not_used_for_rfm": item["image_files"],
                "archive_files_not_double_counted": json.dumps(item["archive_files"], ensure_ascii=False),
            })
        else:
            decisions.append({"dataset": folder, "path": str(path), "decision": "not_found", "training_source": source or "", "reason": "folder not present under data root"})

    write_csv(run_root / "dataset_inventory.csv", inventory,
              ["dataset", "path", "files", "size_bytes", "image_files", "extensions", "archive_files"])
    write_csv(run_root / "source_decisions.csv", decisions,
              ["dataset", "path", "decision", "training_source", "reason", "files", "size_bytes", "image_files_not_used_for_rfm", "archive_files_not_double_counted"])
    (run_root / "schema_evidence.json").write_text(json.dumps(schema_rows, ensure_ascii=False, indent=2), encoding="utf-8")

    trainer = Path(__file__).with_name("train_industry_recommender.py")
    hm_trainer = Path(__file__).with_name("train_hm_full_rfm.py")
    os.environ["PYTHONUTF8"] = "1"

    outputs = []
    command_jobs = [
        ("dunnhumby", [sys.executable, str(trainer), "--source", "dunnhumby", "--max-events", "0", "--data-root", str(root), "--output-root", str(run_root / "models")]),
        ("olist", [sys.executable, str(trainer), "--source", "olist", "--max-events", "0", "--data-root", str(root), "--output-root", str(run_root / "models")]),
        ("online_retail", [sys.executable, str(trainer), "--source", "online_retail", "--max-events", "0", "--data-root", str(root), "--output-root", str(run_root / "models")]),
        ("online_retail_ii", [sys.executable, str(trainer), "--source", "online_retail_ii", "--max-events", "0", "--data-root", str(root), "--output-root", str(run_root / "models")]),
        ("retailrocket", [sys.executable, str(trainer), "--source", "retailrocket", "--max-events", "0", "--data-root", str(root), "--output-root", str(run_root / "models")]),
        ("hm", [sys.executable, str(hm_trainer), "--data-root", str(root), "--output-root", str(run_root / "models")]),
    ]
    suite_log = run_root / "run.log"
    suite_log.write_text(f"suite_started_at_utc: {suite_started}\ndata_root: {root}\n", encoding="utf-8")
    for source, command in command_jobs:
        if source in {"online_retail", "online_retail_ii"}:
            # Dependency can be supplied through the caller's PYTHONPATH.
            temp_dependency = Path(os.environ.get("TEMP", "")) / "smh-rfm-openpyxl-deps"
            if temp_dependency.is_dir():
                current = os.environ.get("PYTHONPATH", "")
                if str(temp_dependency) not in current.split(os.pathsep):
                    os.environ["PYTHONPATH"] = str(temp_dependency) + (os.pathsep + current if current else "")
        output = run_one(source, command, run_root / "logs" / f"{source}.log", run_root)
        outputs.append(output)
        with suite_log.open("a", encoding="utf-8") as stream:
            stream.write(f"{source}: {output['status']} exit={output['exit_code']} duration={output['duration_seconds']}s output={output['output_path']}\n")
        if output["status"] != "completed":
            break

    summary_rows = []
    for result in outputs:
        report = result.get("report") or {}
        clean = report.get("data_cleaning") or {}
        ranker = report.get("supervised_ranker") or {}
        rfm = report.get("rfm") or {}
        summary_rows.append({
            "source": result["source"],
            "status": result["status"],
            "output_path": result["output_path"],
            "rows_seen": clean.get("rows_seen", report.get("rows_seen", report.get("events_read", ""))),
            "rows_accepted": clean.get("rows_accepted", report.get("events_read", "")),
            "customers": report.get("customers", ""),
            "baskets": report.get("baskets", ""),
            "monetary_available": report.get("monetary_available", ""),
            "rfm_clusters": rfm.get("clusters", ""),
            "silhouette_score_sampled": (rfm.get("quality") or {}).get("silhouette_score", (rfm.get("cluster_quality") or {}).get("silhouette_score_sampled", "")),
            "next_basket_ndcg_at_5": (ranker.get("metrics") or {}).get("ndcg_at_5", ""),
            "excluded_counts": json.dumps({k: v for k, v in clean.items() if k.startswith("excluded_") or k.startswith("duplicate_")}, ensure_ascii=False),
        })
    write_csv(run_root / "training_results.csv", summary_rows,
              ["source", "status", "output_path", "rows_seen", "rows_accepted", "customers", "baskets", "monetary_available", "rfm_clusters", "silhouette_score_sampled", "next_basket_ndcg_at_5", "excluded_counts"])
    total_duration = round(time.perf_counter() - suite_clock, 3)
    suite_finished = utc_now()
    suite_report = {
        "started_at_utc": suite_started,
        "finished_at_utc": suite_finished,
        "duration_seconds": total_duration,
        "data_root": str(root),
        "inventory": inventory,
        "top_level_archives": top_level_archives(root),
        "schema_evidence": schema_rows,
        "eligibility_decisions": decisions,
        "training_runs": [
            {k: v for k, v in result.items() if k != "report"}
            | {"report": result.get("report")}
            for result in outputs
        ],
        "production_policy": "benchmark only; never merge public-data customers or activate these artifacts in a live tenant",
    }
    write_csv(run_root / "archive_inventory.csv", suite_report["top_level_archives"],
              ["file", "size_bytes", "matching_extracted_directory", "decision"])
    (run_root / "suite_summary.json").write_text(json.dumps(suite_report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown_report(run_root, suite_report, summary_rows)
    with suite_log.open("a", encoding="utf-8") as stream:
        stream.write(f"suite_finished_at_utc: {suite_finished}\nsuite_duration_seconds: {total_duration}\nsummary: {run_root / 'suite_summary.json'}\n")
    print(json.dumps({"run_root": str(run_root), "finished_at_utc": suite_finished,
                      "duration_seconds": total_duration, "training_results": summary_rows,
                      "decision_counts": dict(Counter(row["decision"] for row in decisions))}, ensure_ascii=False, indent=2), flush=True)
    return 0 if outputs and all(item["status"] == "completed" for item in outputs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
