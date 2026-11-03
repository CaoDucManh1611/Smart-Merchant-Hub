"""Export staff-resolved RAG handoffs as unapproved FAQ candidates.

The export is a review artifact only. It never inserts answers into the
knowledge base or marks any candidate as approved.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database.platform_session import PlatformSessionLocal
from app.database.tenant_session import tenant_session
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.notification import Notification
from app.models.platform_control import TenantRegistry
from app.tenancy.schema import schema_name_for, validate_schema_name


FIELDS = (
    "business_id", "conversation_id", "question_message_id", "staff_message_id",
    "question", "staff_answer", "source_handoff_reason", "review_status",
)


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


def collect_candidates() -> list[dict[str, str]]:
    candidates: dict[tuple[int, int, int], dict[str, str]] = {}
    for business_id, schema in _tenant_rows():
        with tenant_session(schema) as db:
            notifications = db.scalars(select(Notification).where(
                Notification.business_id == business_id,
                Notification.kind == "rag_handoff_required",
            ).order_by(Notification.created_at.asc())).all()
            for note in notifications:
                metadata = note.metadata_ if isinstance(note.metadata_, dict) else {}
                try:
                    conversation_id = int(metadata.get("conversation_id"))
                except (TypeError, ValueError):
                    continue
                conversation = db.get(Conversation, conversation_id)
                if conversation is None or int(conversation.business_id or business_id) != business_id:
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
                key = (business_id, conversation_id, int(latest_inbound.id))
                candidates[key] = {
                    "business_id": str(business_id),
                    "conversation_id": str(conversation_id),
                    "question_message_id": str(latest_inbound.id),
                    "staff_message_id": str(staff.id),
                    "question": str(latest_inbound.content or "").strip(),
                    "staff_answer": str(staff.content or "").strip(),
                    "source_handoff_reason": str(metadata.get("reason") or ""),
                    "review_status": "pending_human_review",
                }
    return sorted(candidates.values(), key=lambda row: (int(row["business_id"]), int(row["conversation_id"]), int(row["question_message_id"])))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = collect_candidates()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"candidate_count": len(rows), "status": "pending_human_review", "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
