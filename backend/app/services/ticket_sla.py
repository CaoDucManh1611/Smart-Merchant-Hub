"""Shop-specific support response and resolution deadlines."""

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.business_setting import BusinessSetting
from app.models.ticket import Ticket, TicketEvent
from app.services.job_service import enqueue_job


SLA_RULES_KEY = "ticket_sla_rules"
DEFAULT_SLA_RULES = {"first_response_hours": 2, "resolution_hours": 24}
LEGACY_PRIORITY_SLA_HOURS = {"low": 72, "normal": 24, "high": 8, "urgent": 4}


def get_sla_rules(db: Session, business_id: int) -> dict[str, int]:
    row = db.query(BusinessSetting).filter(
        BusinessSetting.business_id == business_id,
        BusinessSetting.key == SLA_RULES_KEY,
    ).first()
    if row is None:
        return dict(DEFAULT_SLA_RULES)
    try:
        stored = json.loads(row.value)
        if not isinstance(stored, dict):
            return dict(DEFAULT_SLA_RULES)
        values = {}
        for key, default in DEFAULT_SLA_RULES.items():
            value = stored.get(key, default)
            if type(value) is not int:
                return dict(DEFAULT_SLA_RULES)
            values[key] = value
    except (TypeError, ValueError):
        return dict(DEFAULT_SLA_RULES)
    if not (
        1 <= values["first_response_hours"] <= 168
        and 1 <= values["resolution_hours"] <= 720
    ):
        return dict(DEFAULT_SLA_RULES)
    return values


def save_sla_rules(db: Session, business_id: int, rules: dict[str, int]) -> dict[str, int]:
    normalized = {
        "first_response_hours": int(rules["first_response_hours"]),
        "resolution_hours": int(rules["resolution_hours"]),
    }
    row = db.query(BusinessSetting).filter(
        BusinessSetting.business_id == business_id,
        BusinessSetting.key == SLA_RULES_KEY,
    ).first()
    if row is None:
        db.add(BusinessSetting(
            business_id=business_id,
            key=SLA_RULES_KEY,
            value=json.dumps(normalized, separators=(",", ":")),
        ))
    else:
        row.value = json.dumps(normalized, separators=(",", ":"))
    db.flush()
    return normalized


def ticket_deadlines(
    db: Session,
    business_id: int,
    now: datetime | None = None,
    *,
    priority: str = "normal",
) -> tuple[datetime, datetime]:
    instant = now or datetime.now(timezone.utc).replace(tzinfo=None)
    rules = get_sla_rules(db, business_id)
    configured = db.query(BusinessSetting.id).filter(
        BusinessSetting.business_id == business_id,
        BusinessSetting.key == SLA_RULES_KEY,
    ).first() is not None
    resolution_hours = rules["resolution_hours"] if configured else LEGACY_PRIORITY_SLA_HOURS.get(priority, 24)
    return (
        instant + timedelta(hours=rules["first_response_hours"]),
        instant + timedelta(hours=resolution_hours),
    )


def enqueue_ticket_sla_jobs(db: Session, ticket: Ticket) -> None:
    if ticket.status in ("resolved", "closed"):
        return
    warning_minutes = max(1, int(settings.TICKET_SLA_WARNING_MINUTES))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    deadlines = (
        ("first_response", ticket.first_response_due_at, ticket.first_response_at is None),
        ("resolution", ticket.sla_due_at, True),
    )
    for stage, due_at, is_pending in deadlines:
        if due_at is None or not is_pending:
            continue
        expected_due_at = due_at.isoformat()
        warning_at = max(now, due_at - timedelta(minutes=warning_minutes))
        job_prefix = "ticket" if stage == "resolution" else "ticket.first_response"
        if warning_at < due_at:
            warning_kind = "ticket.sla_warning" if stage == "resolution" else "ticket.first_response.sla_warning"
            warning_key = (
                f"ticket:{ticket.id}:sla-warning:{expected_due_at}"
                if stage == "resolution"
                else f"ticket:{ticket.id}:first-response:sla-warning:{expected_due_at}"
            )
            enqueue_job(
                db,
                business_id=ticket.business_id,
                kind=warning_kind,
                payload={"ticket_id": ticket.id, "sla_due_at": expected_due_at},
                idempotency_key=warning_key,
                run_at=warning_at,
            )
        enqueue_job(
            db,
            business_id=ticket.business_id,
            kind=f"{job_prefix}.sla_check",
            payload={"ticket_id": ticket.id, "sla_due_at": expected_due_at},
            idempotency_key=(
                f"ticket:{ticket.id}:sla:{expected_due_at}"
                if stage == "resolution"
                else f"ticket:{ticket.id}:first-response:sla:{expected_due_at}"
            ),
            run_at=due_at,
        )


def record_first_response(db: Session, conversation_id: int, business_id: int, responded_at: datetime) -> None:
    tickets = db.query(Ticket).filter(
        Ticket.business_id == business_id,
        Ticket.conversation_id == conversation_id,
        Ticket.status.in_(("open", "pending")),
        Ticket.first_response_at.is_(None),
    ).all()
    for ticket in tickets:
        ticket.first_response_at = responded_at
        db.add(TicketEvent(
            business_id=business_id,
            ticket_id=ticket.id,
            event_type="first_response_recorded",
            to_value=responded_at.isoformat(),
        ))
