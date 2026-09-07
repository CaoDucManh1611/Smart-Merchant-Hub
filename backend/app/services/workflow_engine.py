"""Small, deterministic workflow runner for tenant CRM events."""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.business import User
from app.models.conversation import Conversation
from app.models.crm_extended import ConversationAssignment, CustomerTag, Tag
from app.models.customer import Customer
from app.models.ticket import Ticket, TicketEvent
from app.models.workflow import Workflow, WorkflowRun
from app.services.job_service import enqueue_job
from app.tenancy.context import TenantContext


SLA_HOURS = {"low": 72, "normal": 24, "high": 8, "urgent": 4}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _matches(conditions: dict, payload: dict) -> bool:
    return all(payload.get(key) == expected for key, expected in (conditions or {}).items())


def _customer(db: Session, customer_id: int, tenant: TenantContext) -> Customer:
    customer = db.query(Customer).filter(Customer.id == customer_id, Customer.business_id == tenant.business_id).first()
    if customer is None:
        raise ValueError("Customer không thuộc business của workflow.")
    return customer


def _conversation(db: Session, conversation_id: int, tenant: TenantContext) -> Conversation:
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.business_id == tenant.business_id,
    ).first()
    if conversation is None:
        raise ValueError("Conversation không thuộc business của workflow.")
    return conversation


def _active_user(db: Session, user_id: int, tenant: TenantContext) -> User:
    user = db.query(User).filter(
        User.id == user_id,
        User.business_id == tenant.business_id,
        User.is_active.is_(True),
    ).first()
    if user is None:
        raise ValueError("Nhân viên không thuộc business hoặc đã bị vô hiệu hóa.")
    return user


def _run_action(db: Session, action: dict, payload: dict, tenant: TenantContext) -> None:
    action_type = action.get("type")
    if action_type == "create_ticket":
        customer_id = payload.get("customer_id")
        if not customer_id:
            raise ValueError("Action create_ticket cần customer_id trong event payload.")
        customer = _customer(db, int(customer_id), tenant)
        conversation_id = payload.get("conversation_id")
        if conversation_id is not None:
            conversation = _conversation(db, int(conversation_id), tenant)
            if conversation.customer_id != customer.id:
                raise ValueError("Conversation không thuộc customer của workflow.")
        priority = action.get("priority", "normal")
        now = _utcnow()
        ticket = Ticket(
            business_id=tenant.business_id,
            customer_id=customer.id,
            conversation_id=int(conversation_id) if conversation_id is not None else None,
            title=(action.get("title") or "Workflow follow-up").strip(),
            status="open",
            priority=priority,
            sla_due_at=now + timedelta(hours=SLA_HOURS[priority]),
        )
        db.add(ticket)
        db.flush()
        enqueue_job(
            db,
            business_id=tenant.business_id,
            kind="ticket.sla_check",
            payload={"ticket_id": ticket.id},
            idempotency_key=f"ticket:{ticket.id}:sla:{ticket.sla_due_at.isoformat()}",
            run_at=ticket.sla_due_at,
        )
        db.add(TicketEvent(
            business_id=tenant.business_id,
            ticket_id=ticket.id,
            event_type="created",
            to_value=ticket.status,
        ))
        return

    if action_type == "assign_user":
        user_id = action.get("user_id")
        if not user_id:
            raise ValueError("Action assign_user cần user_id.")
        _active_user(db, int(user_id), tenant)
        if payload.get("ticket_id"):
            ticket = db.query(Ticket).filter(
                Ticket.id == int(payload["ticket_id"]),
                Ticket.business_id == tenant.business_id,
            ).first()
            if ticket is None:
                raise ValueError("Ticket không thuộc business của workflow.")
            previous_user_id = ticket.assigned_user_id
            ticket.assigned_user_id = int(user_id)
            if previous_user_id != ticket.assigned_user_id:
                db.add(TicketEvent(
                    business_id=tenant.business_id,
                    ticket_id=ticket.id,
                    event_type="assigned",
                    from_value=str(previous_user_id) if previous_user_id is not None else None,
                    to_value=str(ticket.assigned_user_id),
                ))
        elif payload.get("conversation_id"):
            conversation = _conversation(db, int(payload["conversation_id"]), tenant)
            if conversation.assigned_user_id != int(user_id):
                now = _utcnow()
                for assignment in db.query(ConversationAssignment).filter(
                    ConversationAssignment.conversation_id == conversation.id,
                    ConversationAssignment.unassigned_at.is_(None),
                ).all():
                    assignment.unassigned_at = now
                db.add(ConversationAssignment(
                    conversation_id=conversation.id,
                    user_id=int(user_id),
                    assignment_type="workflow",
                    assigned_at=now,
                ))
            conversation.assigned_user_id = int(user_id)
        else:
            raise ValueError("Action assign_user cần ticket_id hoặc conversation_id.")
        return

    if action_type == "add_tag":
        conversation_id = payload.get("conversation_id")
        customer_id = payload.get("customer_id")
        tag_name = (action.get("tag") or "").strip()
        if not customer_id and conversation_id:
            customer_id = _conversation(db, int(conversation_id), tenant).customer_id
        if not customer_id or not tag_name:
            raise ValueError("Action add_tag cần customer_id và tag.")
        customer = _customer(db, int(customer_id), tenant)
        tag = db.query(Tag).filter(Tag.business_id == tenant.business_id, Tag.name == tag_name).first()
        if tag is None:
            tag = Tag(business_id=tenant.business_id, name=tag_name)
            db.add(tag)
            db.flush()
        exists = db.query(CustomerTag.id).filter(
            CustomerTag.business_id == tenant.business_id,
            CustomerTag.customer_id == customer.id,
            CustomerTag.tag_id == tag.id,
        ).first()
        if exists is None:
            db.add(CustomerTag(
                business_id=tenant.business_id,
                customer_id=customer.id,
                tag_id=tag.id,
            ))
        return

    raise ValueError(f"Workflow action không được hỗ trợ: {action_type}")


def execute_workflow(
    db: Session,
    workflow: Workflow,
    event_id: str,
    event_type: str,
    payload: dict,
    tenant: TenantContext,
    *,
    allow_retry: bool = False,
) -> WorkflowRun:
    existing = db.query(WorkflowRun).filter(
        WorkflowRun.workflow_id == workflow.id,
        WorkflowRun.event_id == event_id,
        WorkflowRun.business_id == tenant.business_id,
    ).first()
    if existing is not None and not (allow_retry and existing.status in {"failed", "scheduled"}):
        return existing

    run = existing or WorkflowRun(
        business_id=tenant.business_id,
        workflow_id=workflow.id,
        event_id=event_id,
        status="skipped",
        matched=False,
        event_type=event_type,
        payload=payload or {},
        attempts=1,
    )
    if existing is not None:
        run.event_type = event_type
        run.payload = payload or {}
        run.attempts = (run.attempts or 0) + 1
        run.error_message = None
        run.next_run_at = None
    if workflow.event_type != event_type or not workflow.enabled or not _matches(workflow.conditions, payload):
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    try:
        for action in workflow.actions or []:
            _run_action(db, action, payload, tenant)
        run.status = "completed"
        run.matched = True
        run.executed_at = _utcnow()
        db.add(run)
        db.commit()
    except Exception as exc:
        db.rollback()
        if existing is not None:
            run = db.get(WorkflowRun, existing.id)
            run.status = "failed"
            run.matched = True
            run.error_message = str(exc)
            run.event_type = event_type
            run.payload = payload or {}
        else:
            run = WorkflowRun(
                business_id=tenant.business_id,
                workflow_id=workflow.id,
                event_id=event_id,
                status="failed",
                matched=True,
                error_message=str(exc),
                event_type=event_type,
                payload=payload or {},
                attempts=(run.attempts or 1),
            )
        db.add(run)
        db.commit()
    db.refresh(run)
    return run


def emit_workflow_event(
    db: Session,
    tenant: TenantContext,
    event_type: str,
    event_id: str,
    payload: dict,
) -> list[WorkflowRun]:
    """Run enabled workflows for one committed CRM event.

    Callers invoke this only after their primary CRM write commits. Each run
    is idempotent on ``workflow_id + event_id`` and remains tenant-scoped.
    """
    workflows = db.query(Workflow).filter(
        Workflow.business_id == tenant.business_id,
        Workflow.event_type == event_type,
        Workflow.enabled.is_(True),
    ).order_by(Workflow.id.asc()).all()
    return [execute_workflow(db, workflow, event_id, event_type, payload, tenant) for workflow in workflows]
