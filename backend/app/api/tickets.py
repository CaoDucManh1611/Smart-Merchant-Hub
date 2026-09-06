"""Tenant-scoped customer support tickets, comments and SLA reporting."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.db.dependencies import get_db
from app.models.business import User
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.ticket import Ticket, TicketComment, TicketEvent
from app.schemas.ticket import (
    TicketCommentCreate,
    TicketCommentOut,
    TicketCreate,
    TicketListOut,
    TicketOut,
    TicketReportOut,
    TicketHistoryEventOut,
    TicketHistoryOut,
    SlaNotificationListOut,
    SlaNotificationOut,
    TicketStatusItem,
    TicketUpdate,
)
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.services.workflow_engine import emit_workflow_event
from app.auth.dependencies import require_write_access
from app.services.notification_service import create_notification
from app.services.audit_service import record_audit


router = APIRouter()
VALID_STATUSES = ("open", "pending", "resolved", "closed")
VALID_PRIORITIES = ("low", "normal", "high", "urgent")
SLA_HOURS = {"low": 72, "normal": 24, "high": 8, "urgent": 4}


def _utcnow() -> datetime:
    """Return a naive UTC datetime matching the existing DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _validate_values(status: str | None, priority: str | None) -> None:
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(status_code=422, detail=f"Status không hợp lệ. Chọn: {', '.join(VALID_STATUSES)}")
    if priority is not None and priority not in VALID_PRIORITIES:
        raise HTTPException(status_code=422, detail=f"Priority không hợp lệ. Chọn: {', '.join(VALID_PRIORITIES)}")


def _customer(db: Session, customer_id: int, tenant: TenantContext) -> Customer:
    customer = db.query(Customer).filter(Customer.id == customer_id, Customer.business_id == tenant.business_id).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer không tồn tại.")
    return customer


def _conversation(db: Session, conversation_id: int, customer_id: int, tenant: TenantContext) -> Conversation:
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.business_id == tenant.business_id,
        Conversation.customer_id == customer_id,
    ).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation không thuộc customer/business này.")
    return conversation


def _assignee(db: Session, user_id: int | None, tenant: TenantContext) -> None:
    if user_id is None:
        return
    user = db.query(User).filter(User.id == user_id, User.business_id == tenant.business_id, User.is_active.is_(True)).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Nhân viên không thuộc business hoặc đã bị vô hiệu hóa.")


def _ticket(db: Session, ticket_id: int, tenant: TenantContext) -> Ticket:
    ticket = db.query(Ticket).options(
        joinedload(Ticket.customer),
        joinedload(Ticket.conversation),
        joinedload(Ticket.comments),
    ).filter(Ticket.id == ticket_id, Ticket.business_id == tenant.business_id).first()
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket không tồn tại.")
    return ticket


def _record_event(
    db: Session,
    ticket: Ticket,
    event_type: str,
    *,
    from_value: str | None = None,
    to_value: str | None = None,
    actor_user_id: int | None = None,
) -> TicketEvent:
    event = TicketEvent(
        business_id=ticket.business_id,
        ticket_id=ticket.id,
        event_type=event_type,
        from_value=from_value,
        to_value=to_value,
        actor_user_id=actor_user_id,
    )
    db.add(event)
    return event


def _out(ticket: Ticket) -> TicketOut:
    comments = sorted(ticket.comments or [], key=lambda comment: comment.created_at or datetime.min)
    return TicketOut(
        id=ticket.id,
        business_id=ticket.business_id,
        customer_id=ticket.customer_id,
        conversation_id=ticket.conversation_id,
        title=ticket.title,
        description=ticket.description,
        status=ticket.status,
        priority=ticket.priority,
        assigned_user_id=ticket.assigned_user_id,
        sla_due_at=ticket.sla_due_at,
        resolved_at=ticket.resolved_at,
        channel=ticket.conversation.channel if ticket.conversation else None,
        customer_name=ticket.customer.name if ticket.customer else None,
        comments=[TicketCommentOut.model_validate(comment) for comment in comments],
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


@router.get("/tickets", response_model=TicketListOut)
def list_tickets(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    status: str | None = None,
    priority: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    _validate_values(status, priority)
    query = db.query(Ticket).options(
        joinedload(Ticket.customer),
        joinedload(Ticket.conversation),
        joinedload(Ticket.comments),
    ).filter(Ticket.business_id == tenant.business_id)
    if status:
        query = query.filter(Ticket.status == status)
    if priority:
        query = query.filter(Ticket.priority == priority)
    total = query.count()
    tickets = query.order_by(Ticket.updated_at.desc(), Ticket.id.desc()).offset(offset).limit(limit).all()
    return TicketListOut(items=[_out(ticket) for ticket in tickets], total=total)


@router.post("/tickets", response_model=TicketOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_ticket(
    payload: TicketCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    _validate_values(payload.status, payload.priority)
    customer = _customer(db, payload.customer_id, tenant)
    conversation = None
    if payload.conversation_id is not None:
        conversation = _conversation(db, payload.conversation_id, customer.id, tenant)
    _assignee(db, payload.assigned_user_id, tenant)
    now = _utcnow()
    resolved_at = now if payload.status in ("resolved", "closed") else None
    due_at = payload.sla_due_at or (now + timedelta(hours=SLA_HOURS[payload.priority]))
    ticket = Ticket(
        business_id=tenant.business_id,
        customer_id=customer.id,
        conversation_id=conversation.id if conversation else None,
        title=payload.title.strip(),
        description=payload.description.strip() if payload.description else None,
        status=payload.status,
        priority=payload.priority,
        assigned_user_id=payload.assigned_user_id,
        sla_due_at=due_at,
        resolved_at=resolved_at,
    )
    db.add(ticket)
    db.commit()
    if ticket.assigned_user_id is not None:
        create_notification(
            db,
            business_id=tenant.business_id,
            user_id=ticket.assigned_user_id,
            kind="ticket_assigned",
            title=f"Ticket mới: {ticket.title}",
            body="Bạn được phân công xử lý ticket này.",
            metadata={"ticket_id": ticket.id, "priority": ticket.priority},
        )
        db.commit()
    _record_event(
        db,
        ticket,
        "created",
        to_value=ticket.status,
        actor_user_id=actor.id if actor else None,
    )
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="ticket_created",
        resource_type="ticket",
        resource_id=ticket.id,
        metadata={
            "customer_id": ticket.customer_id,
            "conversation_id": ticket.conversation_id,
            "priority": ticket.priority,
            "status": ticket.status,
        },
    )
    db.commit()
    emit_workflow_event(
        db,
        tenant,
        "ticket.created",
        f"ticket:{ticket.id}:created",
        {"ticket_id": ticket.id, "customer_id": ticket.customer_id, "conversation_id": ticket.conversation_id, "priority": ticket.priority, "status": ticket.status},
    )
    return _out(_ticket(db, ticket.id, tenant))


@router.patch("/tickets/{ticket_id}", response_model=TicketOut, dependencies=[Depends(require_write_access)])
def update_ticket(
    ticket_id: int,
    payload: TicketUpdate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    ticket = _ticket(db, ticket_id, tenant)
    previous_status = ticket.status
    previous_priority = ticket.priority
    previous_assignee = ticket.assigned_user_id
    data = payload.model_dump(exclude_unset=True)
    _validate_values(data.get("status"), data.get("priority"))
    customer_id = data.get("customer_id", ticket.customer_id)
    _customer(db, customer_id, tenant)
    if customer_id != ticket.customer_id and "conversation_id" not in data:
        data["conversation_id"] = None
    if "conversation_id" in data and data["conversation_id"] is not None:
        _conversation(db, data["conversation_id"], customer_id, tenant)
    _assignee(db, data.get("assigned_user_id", ticket.assigned_user_id), tenant)
    for field, value in data.items():
        setattr(ticket, field, value.strip() if isinstance(value, str) else value)
    if "status" in data:
        if data["status"] in ("resolved", "closed") and ticket.resolved_at is None:
            ticket.resolved_at = _utcnow()
        elif data["status"] in ("open", "pending"):
            ticket.resolved_at = None
    if "status" in data and data["status"] != previous_status:
        _record_event(
            db,
            ticket,
            "status_changed",
            from_value=previous_status,
            to_value=ticket.status,
            actor_user_id=actor.id if actor else None,
        )
    if "priority" in data and data["priority"] != previous_priority:
        _record_event(
            db,
            ticket,
            "priority_changed",
            from_value=previous_priority,
            to_value=ticket.priority,
            actor_user_id=actor.id if actor else None,
        )
    if "assigned_user_id" in data and data["assigned_user_id"] != previous_assignee:
        _record_event(
            db,
            ticket,
            "assigned",
            from_value=str(previous_assignee) if previous_assignee is not None else None,
            to_value=str(ticket.assigned_user_id) if ticket.assigned_user_id is not None else None,
            actor_user_id=actor.id if actor else None,
        )
    if data:
        record_audit(
            db,
            business_id=tenant.business_id,
            user_id=actor.id if actor else None,
            action="ticket_updated",
            resource_type="ticket",
            resource_id=ticket.id,
            metadata={
                "fields": sorted(data.keys()),
                "from_status": previous_status,
                "to_status": ticket.status,
                "from_priority": previous_priority,
                "to_priority": ticket.priority,
                "from_assigned_user_id": previous_assignee,
                "to_assigned_user_id": ticket.assigned_user_id,
            },
        )
    db.commit()
    if "status" in data and data["status"] != previous_status:
        emit_workflow_event(
            db,
            tenant,
            "ticket.status_changed",
            f"ticket:{ticket.id}:status:{ticket.status}",
            {"ticket_id": ticket.id, "customer_id": ticket.customer_id, "conversation_id": ticket.conversation_id, "priority": ticket.priority, "status": ticket.status},
        )
    return _out(_ticket(db, ticket_id, tenant))


@router.post("/tickets/{ticket_id}/comments", response_model=TicketCommentOut, status_code=201, dependencies=[Depends(require_write_access)])
def add_ticket_comment(
    ticket_id: int,
    payload: TicketCommentCreate,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_write_access),
):
    ticket = _ticket(db, ticket_id, tenant)
    comment = TicketComment(
        business_id=tenant.business_id,
        ticket_id=ticket.id,
        body=payload.body.strip(),
        author_user_id=actor.id if actor else None,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    _record_event(
        db,
        ticket,
        "comment_added",
        to_value=str(comment.id),
        actor_user_id=actor.id if actor else None,
    )
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="ticket_comment",
        resource_type="ticket",
        resource_id=ticket.id,
        metadata={"ticket_id": ticket.id, "comment_id": comment.id},
    )
    db.commit()
    return comment


@router.get("/tickets/sla-notifications", response_model=SlaNotificationListOut)
def sla_notifications(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    now = _utcnow()
    tickets = db.query(Ticket).filter(
        Ticket.business_id == tenant.business_id,
        Ticket.sla_due_at.is_not(None),
        Ticket.sla_due_at < now,
        Ticket.status.not_in(("resolved", "closed")),
    ).order_by(Ticket.sla_due_at.asc(), Ticket.id.asc()).all()
    items = [
        SlaNotificationOut(
            ticket_id=ticket.id,
            business_id=ticket.business_id,
            customer_id=ticket.customer_id,
            conversation_id=ticket.conversation_id,
            title=ticket.title,
            priority=ticket.priority,
            status=ticket.status,
            assigned_user_id=ticket.assigned_user_id,
            sla_due_at=ticket.sla_due_at,
            overdue_seconds=max(0, int((now - ticket.sla_due_at).total_seconds())),
        )
        for ticket in tickets
    ]
    return SlaNotificationListOut(items=items, total=len(items))


@router.get("/tickets/{ticket_id}/history", response_model=TicketHistoryOut)
def ticket_history(
    ticket_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    _ticket(db, ticket_id, tenant)
    events = db.query(TicketEvent).filter(
        TicketEvent.ticket_id == ticket_id,
        TicketEvent.business_id == tenant.business_id,
    ).order_by(TicketEvent.created_at.asc(), TicketEvent.id.asc()).all()
    return TicketHistoryOut(
        items=[TicketHistoryEventOut.model_validate(event) for event in events],
        total=len(events),
    )


@router.get("/tickets/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: int, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    return _out(_ticket(db, ticket_id, tenant))


@router.get("/reports/tickets", response_model=TicketReportOut)
def ticket_report(db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    rows = db.query(Ticket.status, func.count(Ticket.id).label("ticket_count")).filter(
        Ticket.business_id == tenant.business_id,
    ).group_by(Ticket.status).order_by(Ticket.status.asc()).all()
    items = [TicketStatusItem(status=row.status, ticket_count=int(row.ticket_count)) for row in rows]
    overdue = db.query(func.count(Ticket.id)).filter(
        Ticket.business_id == tenant.business_id,
        Ticket.sla_due_at.is_not(None),
        Ticket.sla_due_at < _utcnow(),
        Ticket.status.not_in(("resolved", "closed")),
    ).scalar() or 0
    return TicketReportOut(
        items=items,
        total_tickets=sum(item.ticket_count for item in items),
        overdue_tickets=int(overdue),
    )
