"""Pure artifact tests: no tenant sessions, external calls, or real conversations."""
import csv
import io
import json
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.export_rag_faq_candidates import (
    FIELDS, build_candidate, candidate_content_hash, pair_handoff_turn,
)
from scripts.review_rag_feedback import main, review_candidates
from scripts import review_rag_feedback

NOW = datetime(2026, 11, 4, 10, tzinfo=timezone.utc)
CONSENT = {"business_id": 1, "conversation_id": 10, "customer_id": 4,
           "consent_id": 8, "purpose": "faq_reuse", "status": "granted"}


@pytest.fixture(autouse=True)
def current_consent_fixture(monkeypatch):
    # Pure artifact tests inject a current consent result. DB tests below
    # exercise the actual SQL path independently.
    monkeypatch.setattr(review_rag_feedback, "_fresh_consent",
                        lambda business_id, conversation_id: dict(CONSENT))


def message(message_id, direction, sender, content, metadata=None, conversation_id=10):
    return SimpleNamespace(id=message_id, direction=direction, sender_type=sender,
                           content=content, conversation_id=conversation_id, metadata_=metadata or {},
                           sent_at=NOW if direction == "outbound" else None,
                           received_at=NOW if direction == "inbound" else None)


def candidate():
    question = message(10, "inbound", "customer", "Chính sách bảo hành ở shop?")
    bot = message(11, "outbound", "bot", "Nhờ nhân viên xác nhận", {
        "rag_run_id": "run-123", "rag_source_document_ids": [9],
        "source_refs": [{"business_id": 1, "document_id": 9, "chunk_id": 90,
                         "source_kind": "policy", "raw_payload": "NEVER_EXPORT_SECRET"}],
        "error_type": "InsufficientEvidence", "route": "rag_handoff",
        "api_key": "NEVER_EXPORT_SECRET", "error": "NEVER_EXPORT_SECRET",
    })
    staff = message(12, "outbound", "staff", "Nhân viên đã xác nhận điều kiện bảo hành.")
    return build_candidate(1, 10, question, staff, [question, bot, staff],
                           {"reason": "insufficient_evidence"}, CONSENT)


def decision(row, **overrides):
    return {"candidate_id": row["candidate_id"], "content_hash": row["content_hash"],
            "business_id": 1, "decision": "approved", "reviewer_type": "human",
            "reviewer": "staff:42", "reviewed_at": NOW.isoformat(), **overrides}


def rehash(row):
    row["content_hash"] = candidate_content_hash(row)
    row["candidate_id"] = "faq-" + row["content_hash"]
    return row


def test_export_keeps_legacy_columns_and_always_pending_with_stable_hash():
    row = candidate()
    assert FIELDS[:8] == ("business_id", "conversation_id", "question_message_id", "staff_message_id",
                          "question", "staff_answer", "source_handoff_reason", "review_status")
    assert row["review_status"] == "pending_human_review"
    assert row["candidate_id"] == candidate()["candidate_id"]
    assert row["content_hash"] == candidate_content_hash(row)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerow(row)
    restored = next(csv.DictReader(io.StringIO(buffer.getvalue())))
    assert restored == row and candidate_content_hash(restored) == row["content_hash"]


def test_provenance_only_reads_same_turn_bot_allowlist_without_raw_secrets():
    row = candidate()
    assert json.loads(row["bot_message_ids"]) == [11]
    assert json.loads(row["run_ids"]) == ["run-123"]
    assert json.loads(row["error_types"]) == ["InsufficientEvidence"]
    assert json.loads(row["routes"]) == ["rag_handoff"]
    assert {ref["document_id"] for ref in json.loads(row["source_refs"])} == {9}
    assert "NEVER_EXPORT_SECRET" not in json.dumps(row)


def test_new_content_and_provenance_change_candidate_identity():
    row = candidate()
    for key, value in (("staff_answer", "Câu sửa khác"), ("question", "Câu hỏi khác"),
                       ("routes", '["different"]'), ("business_id", "2")):
        changed = {**row, key: value}
        assert candidate_content_hash(changed) != row["content_hash"]


def test_builder_never_reuses_prior_turn_or_foreign_conversation_bot_metadata():
    question = message(10, "inbound", "customer", "Q")
    staff = message(13, "outbound", "staff", "A")
    rows = [message(9, "outbound", "bot", "Old", {"run_id": "old"}), question,
            message(11, "outbound", "bot", "Foreign", {"run_id": "foreign"}, conversation_id=20),
            message(12, "outbound", "bot", "Current", {"run_id": "current"}), staff,
            message(14, "outbound", "bot", "Later", {"run_id": "later"})]
    row = build_candidate(1, 10, question, staff, rows)
    assert json.loads(row["run_ids"]) == ["current"]
    rows.insert(2, message(11, "inbound", "customer", "New question"))
    with pytest.raises(ValueError, match="later turn"):
        build_candidate(1, 10, question, staff, rows)


def test_existing_handoff_pairing_stays_same_turn():
    rows = [message(10, "inbound", "customer", "Q"), message(11, "outbound", "bot", "B"),
            message(12, "outbound", "staff", "A"), message(13, "inbound", "customer", "New Q"),
            message(14, "outbound", "staff", "New A")]
    assert tuple(row.id for row in pair_handoff_turn(rows, NOW, 10)) == (10, 12)


def test_no_decision_or_rejected_decision_produces_no_seed():
    row = candidate()
    assert review_candidates([row], [], 1, NOW) == []
    assert review_candidates([row], [decision(row, decision="rejected")], 1, NOW) == []


def test_only_explicit_human_approval_produces_scoped_seed_and_preserves_inputs():
    row = candidate()
    before = deepcopy(row)
    seeds = review_candidates([row], [decision(row, corrected_answer="Câu trả lời được người duyệt sửa.")], 1, NOW)
    assert len(seeds) == 1 and seeds[0]["review_status"] == "approved"
    assert seeds[0]["answer"] == "Câu trả lời được người duyệt sửa."
    assert seeds[0]["business_id"] == 1 and seeds[0]["source"]["conversation_id"] == 10
    assert seeds[0]["reviewer"] == "staff:42" and seeds[0]["reviewed_at"] == NOW.isoformat()
    assert row == before and row["review_status"] == "pending_human_review"


@pytest.mark.parametrize("override", [
    {"reviewer_type": "ai"}, {"reviewer_type": None}, {"reviewer": ""},
    {"reviewer": "ChatGPT"}, {"reviewer": "AI assistant"}, {"reviewed_at": None},
    {"reviewed_at": "2026-11-04T10:00:00"}, {"reviewed_at": "tomorrow"},
    {"reviewed_at": "2026-11-05T10:00:00+00:00"}, {"decision": "pending"},
    {"business_id": 2}, {"business_id": "1"}, {"content_hash": "old-hash"},
    {"candidate_id": "faq-stale"}, {"corrected_answer": ""}, {"synthetic": True},
])
def test_rejects_missing_or_ai_identity_timestamps_crossshop_stale_and_synthetic_decisions(override):
    row = candidate()
    with pytest.raises(ValueError):
        review_candidates([row], [decision(row, **override)], 1, NOW)


def test_crossshop_candidates_rejected_even_with_human_approval():
    row = rehash({**candidate(), "business_id": "2"})
    with pytest.raises(ValueError, match="cross-shop"):
        review_candidates([row], [decision(row)], 1, NOW)


def test_stale_export_hash_cannot_be_approved_and_status_cannot_self_approve():
    row = candidate()
    with pytest.raises(ValueError, match="stale"):
        review_candidates([{**row, "staff_answer": "Edited after review"}], [decision(row)], 1, NOW)
    with pytest.raises(ValueError, match="unapproved"):
        review_candidates([{**row, "review_status": "approved"}], [decision(row)], 1, NOW)


@pytest.mark.parametrize("change", [{"business_id": 2}, {"conversation_id": 20}, {"synthetic": True}])
def test_foreign_or_synthetic_source_refs_rejected_even_with_fresh_hash(change):
    row = candidate()
    refs = json.loads(row["source_refs"])
    refs[0].update(change)
    row["source_refs"] = json.dumps(refs)
    rehash(row)
    with pytest.raises(ValueError):
        review_candidates([row], [decision(row)], 1, NOW)


@pytest.mark.parametrize("flag", ["synthetic", "is_synthetic", "is_test", "test_data", "offline_evaluation", "evaluation_context"])
@pytest.mark.parametrize("sender", ["customer", "staff", "bot"])
def test_synthetic_flags_from_any_message_block_seeds(flag, sender):
    rows = [message(10, "inbound", "customer", "Q"), message(11, "outbound", "bot", "B"),
            message(12, "outbound", "staff", "A")]
    next(row for row in rows if row.sender_type == sender).metadata_ = {flag: True}
    row = build_candidate(1, 10, rows[0], rows[-1], rows)
    assert row["synthetic"] == "true"
    with pytest.raises(ValueError, match="synthetic"):
        review_candidates([row], [decision(row)], 1, NOW)


def test_duplicate_candidates_and_conflicting_reviews_fail_batch():
    row = candidate()
    with pytest.raises(ValueError, match="duplicate candidate"):
        review_candidates([row, row], [decision(row)], 1, NOW)
    with pytest.raises(ValueError, match="duplicate/conflicting"):
        review_candidates([row], [decision(row), decision(row, decision="rejected")], 1, NOW)


def test_malformed_candidate_fields_and_extra_synthetic_flags_are_rejected():
    for change in ({"staff_message_id": "bad-id"}, {"question": []}, {"is_synthetic": True}):
        row = rehash({**candidate(), **change})
        with pytest.raises(ValueError):
            review_candidates([row], [decision(row)], 1, NOW)


def test_offline_cli_outputs_only_approved_jsonl_and_does_not_overwrite_inputs(tmp_path, monkeypatch, capsys):
    row = candidate()
    candidates = tmp_path / "candidates.csv"
    decisions = tmp_path / "decisions.jsonl"
    output = tmp_path / "seed.jsonl"
    with candidates.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(row)
    decisions.write_text(json.dumps(decision(row)) + "\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["review_rag_feedback.py", "--candidates", str(candidates),
                                      "--decisions", str(decisions), "--business-id", "1", "--output", str(output)])
    assert main() == 0
    assert json.loads(output.read_text(encoding="utf-8"))["review_status"] == "approved"
    assert json.loads(capsys.readouterr().out)["imported"] is False
    decisions.write_text(json.dumps(decision(row, reviewer_type="ai")), encoding="utf-8")
    output.unlink()
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2 and not output.exists()
    assert "NEVER_EXPORT_SECRET" not in capsys.readouterr().err


def test_review_module_import_does_not_load_settings_models_or_databases(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    code = ("import sys; sys.path.insert(0, " + repr(str(backend)) + "); "
            "import scripts.review_rag_feedback; "
            "assert 'app.core.config' not in sys.modules; "
            "assert not any(k.startswith('app.database') for k in sys.modules)")
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
