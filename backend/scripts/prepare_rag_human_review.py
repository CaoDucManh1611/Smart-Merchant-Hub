"""Create a blank human-review sheet from two frozen paired RAG runs."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from scripts.compare_rag_runs import _rows


FIELDS = (
    "case_id", "business_id", "question", "snapshot_id", "snapshot_sha256",
    "model", "sampling_config", "baseline_answer", "candidate_answer",
    "baseline_source_ids", "candidate_source_ids", "gold_source_ids",
    "reviewed_by", "reviewer_type", "reviewed_at", "baseline_correct", "candidate_correct",
    "baseline_hard_error", "candidate_hard_error", "baseline_helpful",
    "candidate_helpful", "review_notes",
)


def prepare(baseline_path: Path, candidate_path: Path, output_path: Path) -> int:
    baseline = _rows(baseline_path)
    candidate = _rows(candidate_path)
    if baseline.keys() != candidate.keys():
        raise ValueError("Case IDs differ between runs")
    rows = []
    for key in sorted(baseline):
        old, new = baseline[key], candidate[key]
        locked = ("business_id", "snapshot_id", "snapshot_sha256", "question_hash", "model", "sampling_config")
        if any(old.get(field) != new.get(field) for field in locked):
            raise ValueError(f"Paired run mismatch: {key}")
        rows.append({
            "case_id": key,
            "business_id": old["business_id"],
            "question": old["question"],
            "snapshot_id": old["snapshot_id"],
            "snapshot_sha256": old["snapshot_sha256"],
            "model": old["model"],
            "sampling_config": json.dumps(old["sampling_config"], ensure_ascii=False, sort_keys=True),
            "baseline_answer": old.get("answer", ""),
            "candidate_answer": new.get("answer", ""),
            "baseline_source_ids": json.dumps(old.get("ranked_source_ids", []), ensure_ascii=False),
            "candidate_source_ids": json.dumps(new.get("ranked_source_ids", []), ensure_ascii=False),
            "gold_source_ids": "",
            "reviewed_by": "",
            "reviewer_type": "",
            "reviewed_at": "",
            "baseline_correct": "",
            "candidate_correct": "",
            "baseline_hard_error": "",
            "candidate_hard_error": "",
            "baseline_helpful": "",
            "candidate_helpful": "",
            "review_notes": "",
        })
    if output_path.exists():
        raise FileExistsError(f"Refuse to overwrite review sheet: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    count = prepare(args.baseline, args.candidate, args.output)
    print(json.dumps({"cases": count, "status": "pending_human_review"}))


if __name__ == "__main__":
    main()
