"""Export staff-resolved RAG handoffs as unapproved FAQ candidates.

The export is a review artifact only. It never inserts answers into the
knowledge base or marks any candidate as approved.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

FIELDS = (
    "business_id", "conversation_id", "question_message_id", "staff_message_id",
    "question", "staff_answer", "source_handoff_reason", "review_status",
    "schema_version", "candidate_id", "content_hash", "bot_message_ids",
    "run_ids", "source_refs", "error_types", "routes", "provenance", "synthetic",
    "consent_provenance",
)
HASH_FIELDS = tuple(key for key in FIELDS if key not in {"candidate_id", "content_hash", "review_status"})


def candidate_content_hash(candidate: dict) -> str:
    """Bind review to all exported content/provenance, stable across CSV roundtrips."""
    payload = {key: str(candidate.get(key, "")) for key in HASH_FIELDS}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _code(value) -> str:
    # Deliberately exclude raw exceptions, prompts, provider payloads and URLs.
    return value if isinstance(value, str) and re.fullmatch(r"[\w.:-]{1,160}", value, re.ASCII) else ""


def _synthetic(metadata: dict) -> bool:
    for key in ("synthetic", "is_synthetic", "is_test", "test_data", "offline_evaluation", "evaluation_context"):
        value = metadata.get(key)
        if value not in (None, False, "", "false", "False", "0", 0):
            return True
    return False


def _trace(metadata: dict, business_id: int) -> dict:
    def codes(keys):
        result = set()
        for key in keys:
            value = metadata.get(key)
            for item in value if isinstance(value, list) else [value]:
                if code := _code(item):
                    result.add(code)
        return sorted(result)

    refs = []
    for key in ("rag_source_document_ids", "source_document_ids"):
        values = metadata.get(key, [])
        if isinstance(values, list):
            refs.extend({"business_id": business_id, "document_id": value}
                        for value in values if type(value) is int and value > 0)
    values = metadata.get("source_refs", [])
    if isinstance(values, list):
        for value in values:
            if not isinstance(value, dict):
                continue
            ref = {key: value[key] for key in ("business_id", "document_id", "chunk_id", "product_id")
                   if type(value.get(key)) is int}
            ref.setdefault("business_id", business_id)
            if source_kind := _code(value.get("source_kind")):
                ref["source_kind"] = source_kind
            if _synthetic(value):
                ref["synthetic"] = True
            refs.append(ref)
    refs = sorted({_json(ref): ref for ref in refs}.values(), key=_json)
    return {"run_ids": codes(("run_id", "rag_run_id", "run_ids", "correlation_id")),
            "source_refs": refs, "error_types": codes(("error_type", "error_route", "error_types")),
            "routes": codes(("route", "execution_route", "catalog_route", "routes")),
            "synthetic": _synthetic(metadata)}


def build_candidate(business_id: int, conversation_id: int, question, staff,
                    messages, handoff_metadata: dict | None = None,
                    consent_provenance: dict | None = None) -> dict[str, str]:
    """Export a same-turn staff correction plus whitelisted bot evidence only."""
    metadata = handoff_metadata or {}
    if type(business_id) is not int or business_id <= 0 or type(conversation_id) is not int or conversation_id <= 0:
        raise ValueError("invalid candidate scope")
    if (question.conversation_id != conversation_id or staff.conversation_id != conversation_id
            or question.direction != "inbound" or question.sender_type != "customer"
            or staff.direction != "outbound" or staff.sender_type != "staff"
            or int(staff.id) <= int(question.id)):
        raise ValueError("candidate must be a scoped customer/staff pair")
    rows = [row for row in messages if row.conversation_id == conversation_id]
    if any(row.direction == "inbound" and row.sender_type == "customer"
           and int(question.id) < int(row.id) < int(staff.id) for row in rows):
        raise ValueError("staff answer belongs to a later turn")
    provenance = []
    synthetic = _synthetic(metadata)
    for row in (question, staff):
        data = row.metadata_ if isinstance(getattr(row, "metadata_", None), dict) else {}
        synthetic |= _synthetic(data)
    for row in sorted(rows, key=lambda row: int(row.id)):
        if not (question.id < row.id < staff.id and row.direction == "outbound" and row.sender_type == "bot"):
            continue
        data = row.metadata_ if isinstance(getattr(row, "metadata_", None), dict) else {}
        trace_business = data.get("business_id", business_id)
        if type(trace_business) is not int:
            trace_business = -1  # Preserve a scope failure without copying arbitrary metadata.
        trace = _trace(data, business_id)
        provenance.append({"message_id": int(row.id), "business_id": trace_business,
                           "conversation_id": conversation_id, **trace})
        synthetic |= trace["synthetic"]
    result = {
        "business_id": str(business_id), "conversation_id": str(conversation_id),
        "question_message_id": str(question.id), "staff_message_id": str(staff.id),
        "question": str(question.content or "").strip(),
        "staff_answer": str(staff.content or "").strip(),
        "source_handoff_reason": _code(metadata.get("reason")),
        "review_status": "pending_human_review", "schema_version": "2",
        "bot_message_ids": _json([item["message_id"] for item in provenance]),
        "run_ids": _json(sorted({value for item in provenance for value in item["run_ids"]})),
        "source_refs": _json(sorted({_json(ref): ref for item in provenance
                                      for ref in item["source_refs"]}.values(), key=_json)),
        "error_types": _json(sorted({value for item in provenance for value in item["error_types"]})),
        "routes": _json(sorted({value for item in provenance for value in item["routes"]})),
        "provenance": _json(provenance), "synthetic": "true" if synthetic else "false",
        "consent_provenance": _json(consent_provenance or {}),
    }
    result["content_hash"] = candidate_content_hash(result)
    result["candidate_id"] = "faq-" + result["content_hash"]
    return result


def _utc_naive(value: datetime | None) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _event_time(message) -> datetime | None:
    if message.direction == "inbound":
        return _utc_naive(message.received_at or message.sent_at)
    return _utc_naive(message.sent_at or message.received_at)


def pair_handoff_turn(messages, handoff_created_at, question_message_id=None):
    """Pair one handoff with its triggering inbound and same-turn staff reply.

    A deterministic inbound id is authoritative. Legacy notifications fall back
    to event time; message ids bound the staff response before the next customer
    message so an answer from a later turn cannot leak into this FAQ candidate.
    """
    ordered = sorted(messages, key=lambda row: int(row.id))
    customer_messages = [
        row for row in ordered
        if row.direction == "inbound" and row.sender_type == "customer"
        and str(row.content or "").strip()
    ]
    question = None
    if question_message_id is not None:
        try:
            target_id = int(question_message_id)
        except (TypeError, ValueError):
            target_id = -1
        question = next((row for row in customer_messages if int(row.id) == target_id), None)
    else:
        handoff_time = _utc_naive(handoff_created_at)
        if handoff_time is not None:
            eligible = [
                row for row in customer_messages
                if (event_time := _event_time(row)) is not None and event_time <= handoff_time
            ]
            question = eligible[-1] if eligible else None
    if question is None:
        return None

    next_customer_id = min(
        (int(row.id) for row in customer_messages if int(row.id) > int(question.id)),
        default=None,
    )
    handoff_time = _utc_naive(handoff_created_at)
    for row in ordered:
        if not (int(row.id) > int(question.id)
                and row.direction == "outbound" and row.sender_type == "staff"
                and str(row.content or "").strip()):
            continue
        if next_customer_id is not None and int(row.id) >= next_customer_id:
            break
        reply_time = _event_time(row)
        if handoff_time is not None and reply_time is not None and reply_time < handoff_time:
            continue
        question_time = _event_time(question)
        if question_time is not None and reply_time is not None and reply_time < question_time:
            continue
        return question, row
    return None


def _tenant_rows() -> list[tuple[int, str]]:
    from app.database.platform_session import PlatformSessionLocal
    from app.models.platform_control import TenantRegistry
    from app.tenancy.schema import schema_name_for, validate_schema_name

    with PlatformSessionLocal() as db:
        rows = db.scalars(select(TenantRegistry).order_by(TenantRegistry.business_id)).all()
    result = []
    for row in rows:
        schema = validate_schema_name(row.schema_name)
        if schema != schema_name_for(int(row.business_id)):
            raise ValueError(f"tenant schema mismatch for business {row.business_id}")
        if str(row.state).casefold() in {"active", "ready", "disabled"}:
            result.append((int(row.business_id), schema))
    return result


def current_consent_provenance(db, business_id: int, conversation_id: int) -> dict | None:
    """Fail closed on missing, foreign, opted-out or revoked current consent.

    FAQ reuse is a separate purpose from per-customer personalization.
    """
    from app.models.conversation import Conversation
    from app.models.customer import Customer
    from app.models.customer_collection import CustomerConsent

    conversation = db.scalars(select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.business_id == business_id,
    ).execution_options(populate_existing=True)).first()
    if conversation is None:
        return None
    customer = db.scalars(select(Customer).where(
        Customer.id == conversation.customer_id,
        Customer.business_id == business_id,
        Customer.fact_extraction_opt_out.is_(False),
        Customer.status == "active",
    ).execution_options(populate_existing=True)).first()
    if customer is None:
        return None
    consent = db.scalars(select(CustomerConsent).where(
        CustomerConsent.business_id == business_id,
        CustomerConsent.customer_id == customer.id,
        CustomerConsent.purpose == "faq_reuse",
    ).order_by(CustomerConsent.id.desc()).limit(1).execution_options(populate_existing=True)).first()
    if consent is None or consent.status != "granted" or consent.revoked_at is not None:
        return None
    return {"business_id": business_id, "conversation_id": conversation_id,
            "customer_id": customer.id, "consent_id": consent.id,
            "purpose": "faq_reuse", "status": "granted"}


def collect_candidates(business_id: int | None = None) -> list[dict[str, str]]:
    # Offline hash/review helpers never initialize application settings/DBs.
    from app.database.tenant_session import tenant_session
    from app.models.conversation import Conversation
    from app.models.message import Message
    from app.models.notification import Notification

    candidates: dict[tuple[int, int, int], dict[str, str]] = {}
    for tenant_business_id, schema in _tenant_rows():
        if business_id is not None and tenant_business_id != business_id:
            continue
        with tenant_session(schema) as db:
            notifications = db.scalars(select(Notification).where(
                Notification.business_id == tenant_business_id,
                Notification.kind == "rag_handoff_required",
            ).order_by(Notification.created_at.asc())).all()
            for note in notifications:
                metadata = note.metadata_ if isinstance(note.metadata_, dict) else {}
                try:
                    conversation_id = int(metadata.get("conversation_id"))
                except (TypeError, ValueError):
                    continue
                conversation = db.get(Conversation, conversation_id)
                if conversation is None or conversation.business_id != tenant_business_id:
                    continue
                consent_provenance = current_consent_provenance(db, tenant_business_id, conversation_id)
                if consent_provenance is None:
                    continue
                messages = db.scalars(select(Message).where(
                    Message.conversation_id == conversation_id,
                    Message.content.is_not(None),
                ).order_by(Message.id.asc())).all()
                paired = pair_handoff_turn(
                    messages,
                    note.created_at,
                    metadata.get("question_message_id"),
                )
                if paired is None:
                    continue
                latest_inbound, staff = paired
                key = (tenant_business_id, conversation_id, int(latest_inbound.id))
                candidates[key] = build_candidate(
                    tenant_business_id, conversation_id, latest_inbound, staff, messages, metadata,
                    consent_provenance,
                )
    return sorted(candidates.values(), key=lambda row: (int(row["business_id"]), int(row["conversation_id"]), int(row["question_message_id"])))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--business-id", type=int, help="Optional single-shop export for review")
    args = parser.parse_args()
    if args.business_id is not None and args.business_id <= 0:
        parser.error("--business-id must be positive")
    rows = collect_candidates() if args.business_id is None else collect_candidates(args.business_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"candidate_count": len(rows), "status": "pending_human_review", "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
