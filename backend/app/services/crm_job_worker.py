"""Durable dispatcher for the CRM jobs owned by tickets and workflows."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.ticket import Ticket
from app.models.workflow import Workflow
from app.services.job_service import dispatch_due_jobs
from app.services.notification_service import create_sla_notification
from app.services.workflow_engine import execute_workflow
from app.services.chatbot_followup import dispatch_due_followups
from app.tenancy.context import TenantContext


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _dispatch_ticket_sla_job(db: Session, business_id: int, payload: dict) -> None:
    ticket_id = int(payload.get("ticket_id") or 0)
    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.business_id == business_id,
    ).first()
    # A deleted, completed, or rescheduled ticket is a successful no-op.  The
    # job has done its job by re-checking the current tenant-owned state.
    if (
        ticket is None
        or ticket.status in {"resolved", "closed"}
        or ticket.sla_due_at is None
        or ticket.sla_due_at > _now()
    ):
        return
    create_sla_notification(
        db,
        business_id=business_id,
        ticket_id=ticket.id,
        user_id=ticket.assigned_user_id,
        title=f"SLA quá hạn: {ticket.title}",
        due_at=ticket.sla_due_at.isoformat(),
    )


def _dispatch_workflow_run_job(db: Session, business_id: int, payload: dict) -> None:
    workflow_id = int(payload.get("workflow_id") or 0)
    workflow = db.query(Workflow).filter(
        Workflow.id == workflow_id,
        Workflow.business_id == business_id,
    ).first()
    if workflow is None:
        # Retrying cannot revive a workflow that the tenant intentionally
        # deleted.  Treat it as a completed no-op rather than poison the queue.
        return
    run = execute_workflow(
        db,
        workflow,
        str(payload["event_id"]),
        str(payload.get("event_type") or workflow.event_type),
        payload.get("event_payload") or {},
        TenantContext(business_id, "job_worker"),
        allow_retry=True,
    )
    if run.status == "failed":
        # execute_workflow records the user-facing failure on WorkflowRun.
        # Raising here also keeps the durable job pending with backoff so a
        # transient failure is retried instead of being silently acknowledged.
        raise RuntimeError(run.error_message or "Workflow run failed")


def _dispatch_chatbot_followup_job(db: Session, business_id: int, payload: dict) -> None:
    result = dispatch_due_followups(db, business_id, limit=1, followup_id=int(payload.get("followup_id") or 0))
    if result.get("failed"):
        raise RuntimeError("Chatbot follow-up delivery failed")


def dispatch_business_crm_jobs(db: Session, business_id: int, *, limit: int = 100) -> int:
    """Run only CRM ticket/workflow jobs for one tenant.

    Filtering the claim query prevents this worker from accidentally retrying
    a RAG or future subsystem's job just because it shares the same table.
    """
    handlers = {
        "ticket.sla_check": lambda payload: _dispatch_ticket_sla_job(db, business_id, payload),
        "workflow.run": lambda payload: _dispatch_workflow_run_job(db, business_id, payload),
        "chatbot.followup": lambda payload: _dispatch_chatbot_followup_job(db, business_id, payload),
    }
    return dispatch_due_jobs(
        db,
        business_id=business_id,
        handlers=handlers,
        kinds=handlers.keys(),
        limit=limit,
    )


def dispatch_all_crm_jobs(db: Session, *, limit_per_business: int = 100) -> int:
    """Dispatch due CRM jobs for every active tenant in one polling cycle."""
    business_ids = db.scalars(select(Business.id).order_by(Business.id.asc())).all()
    return sum(
        dispatch_business_crm_jobs(db, int(business_id), limit=limit_per_business)
        for business_id in business_ids
    )
