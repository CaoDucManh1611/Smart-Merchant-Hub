"""Create approved-only JSONL FAQ seeds from explicit human decisions, offline.

No import or training. Approval rechecks live tenant consent. Candidates are CSV from the
exporter; decisions are JSONL with candidate_id, content_hash, business_id,
decision (approved/rejected), reviewer_type=human, reviewer, reviewed_at (ISO
with timezone), and optionally corrected_answer. The operator authenticates
reviewer identity outside this artifact tool; strings are attestations.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.export_rag_faq_candidates import FIELDS, candidate_content_hash


def _fresh_consent(business_id: int, conversation_id: int) -> dict | None:
    """Read the current tenant registry and consent, never trust CSV claims."""
    from app.database.tenant_session import tenant_session
    from scripts.export_rag_faq_candidates import _tenant_rows, current_consent_provenance

    schema = next((schema for shop, schema in _tenant_rows() if shop == business_id), None)
    if schema is None:
        return None
    with tenant_session(schema) as db:
        return current_consent_provenance(db, business_id, conversation_id)


def _timestamp(value) -> datetime:
    if not isinstance(value, str):
        raise ValueError("reviewed_at must be an explicit ISO timestamp with timezone")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("invalid reviewed_at") from None
    if moment.tzinfo is None:
        raise ValueError("reviewed_at requires timezone")
    return moment.astimezone(timezone.utc)


def _evidence_scope(value, business_id, conversation_id):
    if isinstance(value, dict):
        if "business_id" in value and (type(value["business_id"]) is not int or value["business_id"] != business_id):
            raise ValueError("cross-shop provenance")
        if "conversation_id" in value and (type(value["conversation_id"]) is not int or value["conversation_id"] != conversation_id):
            raise ValueError("cross-conversation provenance")
        for key in ("synthetic", "is_synthetic", "is_test", "test_data", "offline_evaluation", "evaluation_context"):
            if key in value and value[key] not in (False, None, "", "false", "False", "0", 0):
                raise ValueError("synthetic/test feedback cannot become a seed")
        for item in value.values():
            _evidence_scope(item, business_id, conversation_id)
    elif isinstance(value, list):
        for item in value:
            _evidence_scope(item, business_id, conversation_id)


def review_candidates(candidates: list[dict], decisions: list[dict], business_id: int,
                      now: datetime | None = None) -> list[dict]:
    """Fail the batch on malformed/stale/foreign/AI approvals; never infer approval."""
    if type(business_id) is not int or business_id <= 0:
        raise ValueError("business_id must be positive")
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    indexed = {}
    for candidate in candidates:
        if (not isinstance(candidate, dict) or any(key not in candidate for key in FIELDS)
                or any(not isinstance(candidate[key], str) for key in FIELDS)):
            raise ValueError("candidate requires the current export schema")
        if candidate["business_id"] != str(business_id):
            raise ValueError("cross-shop candidate")
        if candidate["schema_version"] != "2" or candidate["review_status"] != "pending_human_review":
            raise ValueError("candidate must be an unapproved schema-2 export")
        digest = candidate_content_hash(candidate)
        if candidate["content_hash"] != digest or candidate["candidate_id"] != "faq-" + digest:
            raise ValueError("stale candidate content hash")
        if candidate["candidate_id"] in indexed:
            raise ValueError("duplicate candidate_id")
        if candidate["synthetic"] != "false":
            raise ValueError("synthetic/test feedback cannot become a seed")
        _evidence_scope({key: candidate[key] for key in (
            "is_synthetic", "is_test", "test_data", "offline_evaluation", "evaluation_context",
        ) if key in candidate}, business_id, 0)
        try:
            for key in ("conversation_id", "question_message_id", "staff_message_id"):
                if int(candidate[key]) <= 0 or str(int(candidate[key])) != candidate[key]:
                    raise ValueError
            conversation_id = int(candidate["conversation_id"])
            evidence = {key: json.loads(candidate[key]) for key in (
                "bot_message_ids", "run_ids", "source_refs", "error_types", "routes", "provenance")}
            consent = json.loads(candidate["consent_provenance"])
        except (ValueError, TypeError):
            raise ValueError("malformed candidate provenance") from None
        if any(not isinstance(value, list) for value in evidence.values()):
            raise ValueError("candidate provenance fields must be lists")
        _evidence_scope(evidence, business_id, conversation_id)
        if (not isinstance(consent, dict) or set(consent) != {
                "business_id", "conversation_id", "customer_id", "consent_id", "purpose", "status"}
                or consent["business_id"] != business_id or consent["conversation_id"] != conversation_id
                or type(consent["customer_id"]) is not int or consent["customer_id"] <= 0
                or type(consent["consent_id"]) is not int or consent["consent_id"] <= 0
                or consent["purpose"] != "faq_reuse" or consent["status"] != "granted"):
            raise ValueError("missing or invalid consent provenance")
        if not candidate["question"].strip() or not candidate["staff_answer"].strip():
            raise ValueError("empty FAQ content")
        indexed[candidate["candidate_id"]] = candidate
    approved = []
    seen = set()
    for decision in decisions:
        if not isinstance(decision, dict):
            raise ValueError("decision must be an object")
        candidate_id = decision.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id not in indexed:
            raise ValueError("unknown/stale decision candidate_id")
        if candidate_id in seen:
            raise ValueError("duplicate/conflicting human decisions")
        seen.add(candidate_id)
        candidate = indexed[candidate_id]
        if type(decision.get("business_id")) is not int or decision["business_id"] != business_id:
            raise ValueError("cross-shop decision")
        if decision.get("content_hash") != candidate["content_hash"]:
            raise ValueError("stale decision content hash")
        reviewer = decision.get("reviewer")
        if (decision.get("reviewer_type") != "human" or not isinstance(reviewer, str)
                or not reviewer.strip() or re.search(r"\b(?:ai|bot|assistant|llm|chatgpt|codex)\b", reviewer, re.I)):
            raise ValueError("explicit human reviewer required; AI-only decisions are forbidden")
        reviewed_at = _timestamp(decision.get("reviewed_at"))
        if reviewed_at > moment:
            raise ValueError("review timestamp is in the future")
        _evidence_scope(decision, business_id, int(candidate["conversation_id"]))
        if decision.get("decision") not in ("approved", "rejected"):
            raise ValueError("decision must explicitly be approved or rejected")
        if decision["decision"] == "rejected":
            continue
        exported_consent = json.loads(candidate["consent_provenance"])
        current_consent = _fresh_consent(business_id, int(candidate["conversation_id"]))
        if current_consent is None or current_consent != exported_consent:
            raise ValueError("consent absent, revoked, changed or foreign at approval")
        answer = decision.get("corrected_answer", candidate["staff_answer"])
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("approved answer cannot be empty")
        approved.append({
            "candidate_id": candidate_id, "content_hash": candidate["content_hash"],
            "business_id": business_id, "question": candidate["question"], "answer": answer.strip(),
            "review_status": "approved", "reviewer_type": "human", "reviewer": reviewer.strip(),
            "reviewed_at": reviewed_at.isoformat(),
            "source": {"conversation_id": int(candidate["conversation_id"]),
                       "question_message_id": int(candidate["question_message_id"]),
                       "staff_message_id": int(candidate["staff_message_id"]),
                       "provenance": json.loads(candidate["provenance"]),
                       "consent_provenance": current_consent},
        })
    return sorted(approved, key=lambda row: row["candidate_id"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--business-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() in {args.candidates.resolve(), args.decisions.resolve()}:
        parser.error("output must not overwrite review inputs")
    try:
        with args.candidates.open(encoding="utf-8-sig", newline="") as handle:
            candidates = list(csv.DictReader(handle))
        with args.decisions.open(encoding="utf-8-sig") as handle:
            decisions = [json.loads(line) for line in handle if line.strip()]
        rows = review_candidates(candidates, decisions, args.business_id)
    except Exception as error:
        # No input content, secret-bearing metadata or answer text in diagnostics.
        parser.exit(2, f"Review validation failed ({type(error).__name__}); no output written.\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({"approved_count": len(rows), "output": str(args.output), "imported": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
