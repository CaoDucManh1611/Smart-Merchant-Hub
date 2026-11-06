import csv
import hashlib
import json

import pytest

from scripts.prepare_rag_human_review import prepare
from scripts.compare_rag_runs import _rows


def _runs(tmp_path, *, mismatch=False):
    question = "Shop còn sản phẩm này không?"
    row = {
        "case_id": "case-1", "business_id": 1, "snapshot_id": "shop-1-v1",
        "snapshot_sha256": "a" * 64, "question": question,
        "question_hash": hashlib.sha256(question.encode()).hexdigest(),
        "model": "fixed-model", "sampling_config": {"temperature": 0},
        "answer": "Câu trả lời A", "ranked_source_ids": ["doc:1#hash"],
    }
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps({"cases": [row]}), encoding="utf-8")
    new = {**row, "answer": "Câu trả lời B"}
    if mismatch:
        new["snapshot_id"] = "shop-1-v2"
    candidate.write_text(json.dumps({"cases": [new]}), encoding="utf-8")
    return baseline, candidate


def test_prepare_creates_blank_non_fake_human_labels(tmp_path):
    output = tmp_path / "review.csv"
    assert prepare(*_runs(tmp_path), output) == 1
    row = next(csv.DictReader(output.open(encoding="utf-8-sig", newline="")))
    assert row["baseline_answer"] == "Câu trả lời A"
    assert row["candidate_answer"] == "Câu trả lời B"
    for field in ("reviewed_by", "reviewer_type", "reviewed_at",
                  "baseline_correct", "candidate_correct",
                  "baseline_hard_error", "candidate_hard_error"):
        assert row[field] == ""
    with pytest.raises(FileExistsError):
        prepare(*_runs(tmp_path), output)


def test_prepare_rejects_unpaired_runs(tmp_path):
    with pytest.raises(ValueError, match="Paired run mismatch"):
        prepare(*_runs(tmp_path, mismatch=True), tmp_path / "review.csv")


def test_prepare_reader_accepts_answer_evaluator_results_shape(tmp_path):
    _, candidate = _runs(tmp_path)
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    candidate.write_text(json.dumps({"results": payload["cases"]}), encoding="utf-8")

    assert _rows(candidate)["case-1"]["answer"] == "Câu trả lời B"
