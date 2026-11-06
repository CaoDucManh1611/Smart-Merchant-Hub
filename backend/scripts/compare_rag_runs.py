"""Compare two frozen, independently reviewed RAG runs without calling providers.

Input files are JSON with ``cases`` rows. Every row must include case_id,
business_id, snapshot_id, snapshot_sha256, question, and metrics. Review labels are a separate CSV with
case_id, business_id, reviewed_by, reviewer_type, reviewed_at, baseline_correct, candidate_correct,
baseline_hard_error, candidate_hard_error, baseline_helpful, candidate_helpful.
This tool deliberately refuses missing human review and mismatched snapshots.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import median


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = (payload.get("cases") or payload.get("results")) if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"No cases in {path}")
    result: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Case must be an object")
        key = str(row.get("case_id") or "").strip()
        if not key or key in result or not row.get("snapshot_id") or not row.get("business_id"):
            raise ValueError(f"Missing/duplicate case identity in {path}: {key}")
        digest = row.get("snapshot_sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"Missing snapshot SHA-256: {key}")
        question = row.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"Missing question: {key}")
        if row.get("question_hash") != hashlib.sha256(question.encode("utf-8")).hexdigest():
            raise ValueError(f"Question SHA-256 mismatch: {key}")
        result[key] = row
    return result


def _review(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result: dict[str, dict] = {}
    for row in rows:
        key = (row.get("case_id") or "").strip()
        if not key or key in result or not (row.get("reviewed_by") or "").strip():
            raise ValueError(f"Missing reviewer or duplicate label: {key}")
        if (row.get("reviewer_type") or "").strip().lower() != "human":
            raise ValueError(f"Review is not attested as human: {key}")
        if not (row.get("reviewed_at") or "").strip():
            raise ValueError(f"Missing human review timestamp: {key}")
        for field in ("baseline_correct", "candidate_correct", "baseline_hard_error",
                      "candidate_hard_error", "baseline_helpful", "candidate_helpful"):
            if (row.get(field) or "").strip().lower() not in {"true", "false"}:
                raise ValueError(f"Unreviewed or invalid {field}: {key}")
            row[field] = row[field].strip().lower() == "true"
        result[key] = row
    return result


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 2)


def _known_sum(rows: list[dict], key: str) -> int | None:
    values = [row.get(key) for row in rows]
    return sum(values) if all(isinstance(value, int) and value >= 0 for value in values) else None


def _retrieval_metrics(ranked: list, gold: list, k: int = 5) -> tuple[float, float]:
    if not gold:
        raise ValueError("Gold source list must be nonempty")
    relevant = set(gold)
    hits = [item in relevant for item in ranked[:k]]
    recall = sum(hits) / len(relevant)
    dcg = sum(int(hit) / math.log2(index + 2) for index, hit in enumerate(hits))
    ideal = sum(1 / math.log2(index + 2) for index in range(min(len(relevant), k)))
    return round(recall, 6), round(dcg / ideal, 6)


def _summary(cases: list[dict], min_cases: int, max_p95_ms: float | None,
             max_cost_usd_per_case: float | None) -> dict:
    count = len(cases)
    labels = [row["review"] for row in cases]
    baseline = [row["baseline"] for row in cases]
    candidate = [row["candidate"] for row in cases]
    result = {"cases": count, "sufficient_cases": count >= min_cases}
    for arm, runs in (("baseline", baseline), ("candidate", candidate)):
        times = [float(row["latency_ms"]) for row in runs
                 if isinstance(row.get("latency_ms"), (int, float)) and row["latency_ms"] >= 0]
        retrieval = [
            _retrieval_metrics(run["ranked_source_ids"], case["gold_source_ids"])
            for case, run in zip(cases, runs)
            if isinstance(case["gold_source_ids"], list) and case["gold_source_ids"]
            and isinstance(run.get("ranked_source_ids"), list)
        ]
        result[arm] = {
            "correct": sum(label[f"{arm}_correct"] for label in labels),
            "hard_errors": sum(label[f"{arm}_hard_error"] for label in labels),
            "helpful": sum(label[f"{arm}_helpful"] for label in labels),
            "p50_ms": round(median(times), 2) if len(times) == count else None,
            "p95_ms": _percentile(times, .95) if len(times) == count else None,
            "tokens": _known_sum(runs, "tokens"),
            "llm_calls": _known_sum(runs, "llm_calls"),
            "fallback_count": sum(bool(row["fallback_used"]) for row in runs)
            if all(isinstance(row.get("fallback_used"), bool) for row in runs) else None,
            "retrieval_scored_cases": len(retrieval),
            "recall_at_5": round(sum(item[0] for item in retrieval) / len(retrieval), 6) if retrieval else None,
            "ndcg_at_5": round(sum(item[1] for item in retrieval) / len(retrieval), 6) if retrieval else None,
            "cost_usd": round(sum(row["cost_usd"] for row in runs), 6)
            if all(isinstance(row.get("cost_usd"), (int, float)) and row["cost_usd"] >= 0 for row in runs)
            else None,
        }
    old, new = result["baseline"], result["candidate"]
    result["gate"] = (
        "INSUFFICIENT" if count < min_cases else
        "FAIL" if new["hard_errors"] > old["hard_errors"] or new["hard_errors"] > 0
        or new["helpful"] < old["helpful"] else "PASS_OFFLINE"
    )
    if result["gate"] == "PASS_OFFLINE":
        if (max_p95_ms is not None and new["p95_ms"] is None) or (
            max_cost_usd_per_case is not None and new["cost_usd"] is None
        ):
            result["gate"] = "INCOMPLETE_TELEMETRY"
        elif ((max_p95_ms is not None and new["p95_ms"] > max_p95_ms)
              or (max_cost_usd_per_case is not None
                  and new["cost_usd"] / count > max_cost_usd_per_case)):
            result["gate"] = "FAIL_PERFORMANCE"
    return result


def compare(baseline_path: Path, candidate_path: Path, labels_path: Path, min_cases: int = 30,
            *, max_p95_ms: float | None = None,
            max_cost_usd_per_case: float | None = None) -> dict:
    if min_cases < 1:
        raise ValueError("min_cases must be positive")
    if max_p95_ms is not None and max_p95_ms <= 0:
        raise ValueError("max_p95_ms must be positive")
    if max_cost_usd_per_case is not None and max_cost_usd_per_case < 0:
        raise ValueError("max_cost_usd_per_case must be nonnegative")
    baseline, candidate, labels = _rows(baseline_path), _rows(candidate_path), _review(labels_path)
    if not baseline.keys() == candidate.keys() == labels.keys():
        raise ValueError("Case IDs differ between runs and approved labels")
    paired: list[dict] = []
    for key in sorted(baseline):
        old, new, label = baseline[key], candidate[key], labels[key]
        if (old["business_id"] != new["business_id"] or old["snapshot_id"] != new["snapshot_id"]
                or old["snapshot_sha256"] != new["snapshot_sha256"]
                or str(label.get("business_id")) != str(old["business_id"])):
            raise ValueError(f"Tenant/snapshot mismatch: {key}")
        if old.get("question_hash") != new.get("question_hash") or not old.get("question_hash"):
            raise ValueError(f"Question changed or hash missing: {key}")
        if old.get("sampling_config") != new.get("sampling_config"):
            raise ValueError(f"Sampling configuration changed: {key}")
        if old.get("model") != new.get("model") or not old.get("model"):
            raise ValueError(f"LLM model changed: {key}")
        try:
            gold = json.loads(label.get("gold_source_ids") or "[]")
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid gold_source_ids: {key}") from error
        if not isinstance(gold, list):
            raise ValueError(f"Invalid gold_source_ids: {key}")
        paired.append({"case_id": key, "business_id": int(old["business_id"]),
                       "gold_source_ids": gold,
                       "baseline": old, "candidate": new, "review": label})
    shops = sorted({row["business_id"] for row in paired})
    per_shop = {str(shop): _summary([row for row in paired if row["business_id"] == shop],
                                    min_cases, max_p95_ms, max_cost_usd_per_case)
                for shop in shops}
    overall = _summary(paired, min_cases, max_p95_ms, max_cost_usd_per_case)
    if any(item["gate"] == "INSUFFICIENT" for item in per_shop.values()):
        overall["gate"] = "INSUFFICIENT_PER_SHOP"
    elif any(item["gate"] == "FAIL" for item in per_shop.values()):
        overall["gate"] = "FAIL_PER_SHOP"
    elif any(item["gate"] != "PASS_OFFLINE" for item in per_shop.values()):
        overall["gate"] = "BLOCKED_PER_SHOP"
    return {
        "status": "offline_human_reviewed_comparison",
        "input_sha256": {"baseline": _digest(baseline_path), "candidate": _digest(candidate_path),
                         "labels": _digest(labels_path)},
        "predeclared_limits": {"min_cases_per_shop": min_cases, "max_p95_ms": max_p95_ms,
                               "max_cost_usd_per_case": max_cost_usd_per_case},
        "overall": overall,
        "per_shop": per_shop,
        "case_pairs": [{"case_id": row["case_id"], "business_id": row["business_id"],
                        "baseline_correct": row["review"]["baseline_correct"],
                        "candidate_correct": row["review"]["candidate_correct"],
                        "baseline_hard_error": row["review"]["baseline_hard_error"],
                        "candidate_hard_error": row["review"]["candidate_hard_error"]}
                       for row in paired],
        "limitations": ["No live channel/provider validation", "Unknown usage/cost remains null",
                        "PASS_OFFLINE requires separate staging and per-shop rollout gates"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-cases-per-shop", type=int, default=30)
    parser.add_argument("--max-p95-ms", type=float)
    parser.add_argument("--max-cost-usd-per-case", type=float)
    args = parser.parse_args()
    report = compare(args.baseline, args.candidate, args.labels, args.min_cases_per_shop,
                     max_p95_ms=args.max_p95_ms,
                     max_cost_usd_per_case=args.max_cost_usd_per_case)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"overall": report["overall"]["gate"],
                      "per_shop": {key: value["gate"] for key, value in report["per_shop"].items()}}))


if __name__ == "__main__":
    main()
