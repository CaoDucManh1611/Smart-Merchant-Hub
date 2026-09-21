"""Durable dispatcher for CRM and knowledge-base background jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ticket import Ticket
from app.models.workflow import Workflow
from app.models.notification import Notification
from app.models.platform_control import TenantRegistry
from app.services.job_service import dispatch_due_jobs
from app.services.notification_service import create_sla_notification, create_sla_warning_notification, deliver_notification_email
from app.services.workflow_engine import execute_workflow
from app.services.chatbot_followup import dispatch_due_followups
from app.services.order_service import release_expired_draft_reservations
from app.services.rag_job_service import dispatch_rag_job
from app.tenancy.context import TenantContext
from app.tenancy.schema import schema_name_for, validate_schema_name


@dataclass(frozen=True)
class TenantJobEnvelope:
    """Minimal queue payload used to re-bind a job to a shop schema."""

    business_id: int
    schema_name: str
    job_id: int


def resolve_job_tenant(envelope: TenantJobEnvelope, *, registry_lookup) -> str:
    """Resolve an active schema from the platform registry.

    The schema in a queue message is an integrity check, never an authority.
    """
    expected = schema_name_for(envelope.business_id)
    supplied = validate_schema_name(envelope.schema_name)
    if supplied != expected:
        raise PermissionError("Tenant job schema does not match business")
    registry = registry_lookup(envelope.business_id)
    if registry is None:
        raise PermissionError("Tenant registry entry not found")
    state = getattr(registry, "state", None)
    registered_schema = getattr(registry, "schema_name", supplied)
    if state != "active" or validate_schema_name(str(registered_schema)) != expected:
        raise PermissionError("Tenant is not active")
    return expected


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _dispatch_ticket_sla_job(db: Session, business_id: int, payload: dict) -> None:
    ticket_id = int(payload.get("ticket_id") or 0)
    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.business_id == business_id,
    ).first()
    expected_due_at = str(payload.get("sla_due_at") or "")
    # A deleted, completed, or rescheduled ticket is a successful no-op.  The
    # job has done its job by re-checking the current tenant-owned state.
    if (
        ticket is None
        or ticket.status in {"resolved", "closed"}
        or ticket.sla_due_at is None
        or (expected_due_at and ticket.sla_due_at.isoformat() != expected_due_at)
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


def _dispatch_ticket_sla_warning_job(db: Session, business_id: int, payload: dict) -> None:
    ticket_id = int(payload.get("ticket_id") or 0)
    ticket = db.query(Ticket).filter(
        Ticket.id == ticket_id,
        Ticket.business_id == business_id,
    ).first()
    expected_due_at = str(payload.get("sla_due_at") or "")
    if (
        ticket is None
        or ticket.status in {"resolved", "closed"}
        or ticket.sla_due_at is None
        or (expected_due_at and ticket.sla_due_at.isoformat() != expected_due_at)
        or ticket.sla_due_at <= _now()
    ):
        return
    create_sla_warning_notification(
        db,
        business_id=business_id,
        ticket_id=ticket.id,
        user_id=ticket.assigned_user_id,
        title=f"SLA sắp đến hạn: {ticket.title}",
        due_at=ticket.sla_due_at.isoformat(),
    )


def _dispatch_workflow_run_job(db: Session, business_id: int, payload: dict, *, platform_db: Session | None = None) -> None:
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
        platform_db=platform_db,
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


def _dispatch_notification_email_job(db: Session, business_id: int, payload: dict) -> None:
    """Retry a staff handoff email without exposing tenant data to the queue."""
    notification_id = int(payload.get("notification_id") or 0)
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.business_id == business_id,
    ).first()
    if notification is None:
        return
    metadata = dict(notification.metadata_ or {})
    if metadata.get("email_status") == "sent":
        return
    sent = deliver_notification_email(
        recipient_email=payload.get("recipient_email"),
        title=str(payload.get("title") or notification.title),
        body=str(payload.get("body") or notification.body or ""),
    )
    if not sent:
        raise RuntimeError("Chưa gửi được email thông báo; kiểm tra cấu hình SMTP.")
    notification.metadata_ = {**metadata, "email_status": "sent"}


def dispatch_business_crm_jobs(db: Session, business_id: int, *, limit: int = 100, platform_db: Session | None = None) -> int:
    """Run CRM and knowledge-base jobs for one tenant.

    Filtering the claim query keeps the worker explicit about the job kinds it
    owns while allowing large RAG imports to run outside the API process.
    """
    # Draft reservations are intentionally cleaned on every polling cycle so
    # a missed follow-up job cannot leave stock blocked indefinitely.
    released_reservations = release_expired_draft_reservations(db, business_id)
    if released_reservations:
        db.commit()

    handlers = {
        "rag.ingest": lambda payload: dispatch_rag_job(db, payload, business_id),
        "ticket.sla_warning": lambda payload: _dispatch_ticket_sla_warning_job(db, business_id, payload),
        "ticket.sla_check": lambda payload: _dispatch_ticket_sla_job(db, business_id, payload),
        "workflow.run": lambda payload: _dispatch_workflow_run_job(db, business_id, payload, platform_db=platform_db),
        "chatbot.followup": lambda payload: _dispatch_chatbot_followup_job(db, business_id, payload),
        "notification.email": lambda payload: _dispatch_notification_email_job(db, business_id, payload),
    }
    processed_jobs = dispatch_due_jobs(
        db,
        business_id=business_id,
        handlers=handlers,
        kinds=handlers.keys(),
        limit=limit,
    )
    return processed_jobs + released_reservations


def dispatch_all_crm_jobs(platform_db: Session, *, tenant_session_factory=None, limit_per_business: int = 100) -> int:
    """Dispatch jobs by active registry entries, one isolated session each.

    ``tenant_session_factory`` is mandatory for the SaaS worker.  The
    no-factory path is retained solely for legacy SQLite fixtures during the
    staged rollout and is never used by the production worker entrypoint.
    """
    if tenant_session_factory is None:
        # Legacy tests/databases have no control-plane registry yet. Process
        # only business ids already present in their job table and keep the
        # compatibility path explicit.
        from app.models.crm_job import CrmJob

        business_ids = [int(value) for value in platform_db.scalars(select(CrmJob.business_id).distinct()).all()]
        return sum(
            dispatch_business_crm_jobs(platform_db, business_id, limit=limit_per_business, platform_db=platform_db)
            for business_id in business_ids
        )

    registries = platform_db.scalars(
        select(TenantRegistry).where(
            TenantRegistry.state == "active",
            TenantRegistry.feature_enabled.is_(True),
        ).order_by(TenantRegistry.business_id.asc())
    ).all()
    processed = 0
    for registry in registries:
        envelope = TenantJobEnvelope(
            business_id=int(registry.business_id),
            schema_name=str(registry.schema_name),
            job_id=0,
        )
        schema = resolve_job_tenant(envelope, registry_lookup=lambda _id, row=registry: row)
        try:
            with tenant_session_factory(schema) as tenant_db:
                processed += dispatch_business_crm_jobs(
                    tenant_db,
                    envelope.business_id,
                    limit=limit_per_business,
                    platform_db=platform_db,
                )
        finally:
            # Explicitly clear any identity-map state before the next shop;
            # the context manager still owns commit/rollback/close semantics.
            platform_db.expire_all()
    return processed
