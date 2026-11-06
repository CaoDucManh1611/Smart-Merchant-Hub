import csv
import hashlib
import json
from pathlib import Path

import pytest

from scripts.compare_rag_runs import compare


FIELDS = ("case_id", "business_id", "reviewed_by", "reviewer_type", "reviewed_at",
          "baseline_correct", "candidate_correct",
          "baseline_hard_error", "candidate_hard_error", "baseline_helpful", "candidate_helpful")


def _fixture(tmp_path: Path, *, changed_snapshot=False, missing_usage=False):
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    labels = tmp_path / "labels.csv"
    base_rows = [{"case_id": f"case-{n}", "business_id": 1, "snapshot_id": "fixed-v1",
                  "snapshot_sha256": "a" * 64, "question": f"Question {n}",
                  "question_hash": hashlib.sha256(f"Question {n}".encode()).hexdigest(),
                  "sampling_config": {"temperature": 0},
                  "model": "same-model", "latency_ms": 100,
                  "tokens": 10, "llm_calls": 1, "cost_usd": 0.01} for n in range(3)]
    new_rows = [{**row, "latency_ms": 80} for row in base_rows]
    if changed_snapshot:
        new_rows[0]["snapshot_id"] = "other-shop-snapshot"
    if missing_usage:
        new_rows[0].pop("tokens")
    baseline.write_text(json.dumps({"cases": base_rows}), encoding="utf-8")
    candidate.write_text(json.dumps({"cases": new_rows}), encoding="utf-8")
    with labels.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for n in range(3):
            writer.writerow({"case_id": f"case-{n}", "business_id": 1,
                             "reviewed_by": "reviewer@example.test", "reviewer_type": "human",
                             "reviewed_at": "2026-11-04T12:00:00+07:00",
                             "baseline_correct": "false", "candidate_correct": "true",
                             "baseline_hard_error": "false", "candidate_hard_error": "false",
                             "baseline_helpful": "false", "candidate_helpful": "true"})
    return baseline, candidate, labels


def test_paired_review_and_per_shop_gate(tmp_path):
    paths = _fixture(tmp_path)
    report = compare(*paths, min_cases=3)
    assert report["per_shop"]["1"]["gate"] == "PASS_OFFLINE"
    assert report["per_shop"]["1"]["candidate"]["p95_ms"] == 80
    assert report["per_shop"]["1"]["candidate"]["correct"] == 3
    assert compare(*paths, min_cases=4)["per_shop"]["1"]["gate"] == "INSUFFICIENT"


def test_snapshot_mismatch_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="snapshot mismatch"):
        compare(*_fixture(tmp_path, changed_snapshot=True))


def test_missing_usage_is_unknown_not_zero(tmp_path):
    report = compare(*_fixture(tmp_path, missing_usage=True), min_cases=3)
    assert report["per_shop"]["1"]["candidate"]["tokens"] is None


def test_unreviewed_or_hard_error_blocks_gate(tmp_path):
    baseline, candidate, labels = _fixture(tmp_path)
    text = labels.read_text(encoding="utf-8").replace(
        "2026-11-04T12:00:00+07:00,false,true,false,false,false,true",
        "2026-11-04T12:00:00+07:00,false,true,false,true,false,true", 1,
    )
    labels.write_text(text, encoding="utf-8")
    assert compare(baseline, candidate, labels, min_cases=3)["per_shop"]["1"]["gate"] == "FAIL"
    labels.write_text(text.replace("reviewer@example.test,human", ",human", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="reviewer"):
        compare(baseline, candidate, labels, min_cases=3)


def test_ai_or_unattested_review_is_rejected(tmp_path):
    baseline, candidate, labels = _fixture(tmp_path)
    text = labels.read_text(encoding="utf-8")
    labels.write_text(text.replace(",human,2026-11-04", ",ai,2026-11-04", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="not attested as human"):
        compare(baseline, candidate, labels, min_cases=3)

    labels.write_text(text.replace(",2026-11-04T12:00:00+07:00,", ",,", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="review timestamp"):
        compare(baseline, candidate, labels, min_cases=3)


def test_retrieval_metrics_only_with_reviewed_gold(tmp_path):
    baseline, candidate, labels = _fixture(tmp_path)
    for path, ranked in ((baseline, ["wrong", "gold"]), (candidate, ["gold", "wrong"])):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["cases"][0]["ranked_source_ids"] = ranked
        path.write_text(json.dumps(payload), encoding="utf-8")
    rows = list(csv.DictReader(labels.open(encoding="utf-8", newline="")))
    rows[0]["gold_source_ids"] = '["gold"]'
    with labels.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=(*FIELDS, "gold_source_ids"))
        writer.writeheader()
        writer.writerows(rows)
    report = compare(baseline, candidate, labels, min_cases=3)
    assert report["per_shop"]["1"]["baseline"]["recall_at_5"] == 1
    assert report["per_shop"]["1"]["baseline"]["ndcg_at_5"] < report["per_shop"]["1"]["candidate"]["ndcg_at_5"]
    assert report["per_shop"]["1"]["candidate"]["retrieval_scored_cases"] == 1


def test_predeclared_latency_and_cost_limits(tmp_path):
    baseline, candidate, labels = _fixture(tmp_path)
    assert compare(baseline, candidate, labels, 3, max_p95_ms=70)["per_shop"]["1"]["gate"] == "FAIL_PERFORMANCE"
    assert compare(baseline, candidate, labels, 3, max_cost_usd_per_case=.001)["per_shop"]["1"]["gate"] == "FAIL_PERFORMANCE"
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    payload["cases"][0].pop("cost_usd")
    candidate.write_text(json.dumps(payload), encoding="utf-8")
    assert compare(baseline, candidate, labels, 3, max_cost_usd_per_case=.02)["per_shop"]["1"]["gate"] == "INCOMPLETE_TELEMETRY"
