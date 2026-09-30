"""Tenant-scoped CRM reporting endpoints."""

import csv
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.tenancy.crm_session import get_tenant_db
from app.database.platform_session import get_platform_db
from app.db.dependencies import get_db
from app.models.business import User
from app.models.industry_modules import Appointment, AppointmentService, CommercialInvoice, CommercialProject, CommercialQuote
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.lead import Lead
from app.models.sales import Order, Product
from app.models.ticket import Ticket
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order import PurchaseOrderItem
from app.models.inventory import PurchaseReceipt, PurchaseReceiptItem, StockMovement
from app.models.channel import Channel, ChannelEvent
from app.models.rag_run import RagRun
from app.models.audit_log import AuditLog
from app.models.saas import SaaSUsage
from app.models.business import ServicePlan, Subscription
from app.models.platform_control import PlatformServicePlan, PlatformSubscription, PlatformUsage
from app.services.channel_retry import provider_breaker_snapshot
from app.services.quota_service import PLAN_LIMIT_FIELDS, quota_period_start
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context


router = APIRouter()
REVENUE_ORDER_STATUSES = ("confirmed", "processing", "shipped", "delivered", "completed", "paid")


def _number(value):
    """Serialize quota counters without leaking Decimal objects to JSON."""
    if value is None:
        return None
    number = Decimal(str(value))
    integer = int(number)
    return integer if number == integer else float(number)


class CrmOverviewOut(BaseModel):
    customer_count: int
    conversation_count: int
    ticket_count: int
    open_ticket_count: int
    lead_count: int
    won_lead_count: int
    order_count: int
    total_revenue: Decimal
    conversion_rate: float
    conversation_to_order_rate: float
    channel_breakdown: list[dict] = Field(default_factory=list)
    time_series: list[dict] = Field(default_factory=list)
    purchase_order_count: int = 0
    purchase_spend: Decimal = Decimal("0")


class AgentPerformanceItem(BaseModel):
    user_id: int
    full_name: str
    role: str
    assigned_conversations: int
    assigned_tickets: int
    resolved_tickets: int
    assigned_leads: int
    won_leads: int


class AgentPerformanceOut(BaseModel):
    items: list[AgentPerformanceItem]


def _active_plan(platform_db: Session, business_id: int):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Plan/subscription metadata is control-plane data.  Never issue this
    # query through a tenant-bound session: a tenant schema intentionally has
    # no service_plans or subscriptions tables.
    try:
        native = platform_db.query(PlatformServicePlan).join(
            PlatformSubscription,
            PlatformSubscription.plan_id == PlatformServicePlan.id,
        ).filter(
            PlatformSubscription.business_id == business_id,
            PlatformSubscription.status == "active",
            (PlatformSubscription.starts_at.is_(None) | (PlatformSubscription.starts_at <= now)),
            (PlatformSubscription.ends_at.is_(None) | (PlatformSubscription.ends_at > now)),
        ).order_by(PlatformSubscription.id.desc()).first()
        if native is not None:
            return native
    except Exception:
        # During the staged rollout a platform database may still expose the
        # legacy control tables.  Clear the failed transaction before using
        # that explicitly scoped compatibility path.
        platform_db.rollback()
    return platform_db.query(ServicePlan).join(Subscription, Subscription.plan_id == ServicePlan.id).filter(
        Subscription.business_id == business_id,
        Subscription.status == "active",
        (Subscription.starts_at.is_(None) | (Subscription.starts_at <= now)),
        (Subscription.ends_at.is_(None) | (Subscription.ends_at > now)),
    ).order_by(Subscription.id.desc()).first()


def _plan_limit(plan, field: str):
    """Read one quota from either the native or rollout plan shape."""
    value = getattr(plan, field, None)
    if value is not None:
        return value
    quotas = getattr(plan, "quotas", None)
    if isinstance(quotas, dict):
        return quotas.get(field.removeprefix("max_"), quotas.get(field))
    return None


def _platform_usage_rows(platform_db: Session, business_id: int, period_start):
    """Return platform-owned usage counters without touching tenant tables."""
    try:
        rows = platform_db.query(PlatformUsage).filter(
            PlatformUsage.business_id == business_id,
            PlatformUsage.period_start == period_start,
        ).all()
        if rows:
            return rows
    except Exception:
        platform_db.rollback()
    return platform_db.query(SaaSUsage).filter(
        SaaSUsage.business_id == business_id,
        SaaSUsage.period_start == period_start,
    ).all()


@router.get("/reports/quality")
def quality_dashboard(
    db: Session = Depends(get_tenant_db),
    platform_db: Session = Depends(get_platform_db),
    tenant: TenantContext = Depends(get_tenant_context),
    days: int = Query(default=30, ge=1, le=365),
):
    """Return one tenant-scoped operations snapshot for the CRM dashboard.

    Usage is read-only, while provider and AI signals are aggregated from the
    durable channel/RAG/audit records.  The response intentionally contains
    counters and redacted state only; no customer message or secret is
    returned.
    """
    business_id = tenant.business_id
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=int(days))
    period_start = quota_period_start()
    usage_rows = _platform_usage_rows(platform_db, business_id, period_start)
    used = {row.resource: _number(row.used or 0) for row in usage_rows}
    plan = _active_plan(platform_db, business_id)
    usage = {}
    for resource, field in PLAN_LIMIT_FIELDS.items():
        current = used.get(resource, 0)
        raw_limit = _plan_limit(plan, field) if plan is not None else None
        limit = _number(raw_limit) if raw_limit is not None else None
        usage[resource] = {
            "used": current,
            "limit": limit,
            "remaining": max(0, limit - current) if limit is not None else None,
        }

    failed_events = db.query(ChannelEvent).join(Channel).filter(
        Channel.business_id == business_id,
        ChannelEvent.status == "failed",
        ChannelEvent.received_at >= since,
    ).count()
    retrying_events = db.query(ChannelEvent).join(Channel).filter(
        Channel.business_id == business_id,
        ChannelEvent.status.in_(("received", "processing")),
        ChannelEvent.received_at >= since,
    ).count()
    rag_runs = db.query(RagRun).filter(
        RagRun.business_id == business_id,
        RagRun.created_at >= since,
    ).all()
    rag_errors = sum(1 for run in rag_runs if run.status in {"failed", "error"})
    tool_errors = db.query(AuditLog).filter(
        AuditLog.business_id == business_id,
        AuditLog.created_at >= since,
        AuditLog.action.in_(("chatbot_tool_error", "chatbot_order_tool_error")),
    ).count()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    open_tickets = db.query(Ticket).filter(
        Ticket.business_id == business_id,
        ~Ticket.status.in_(("resolved", "closed")),
    ).count()
    overdue_tickets = db.query(Ticket).filter(
        Ticket.business_id == business_id,
        ~Ticket.status.in_(("resolved", "closed")),
        Ticket.sla_due_at.is_not(None),
        Ticket.sla_due_at < now,
    ).count()
    due_soon_tickets = db.query(Ticket).filter(
        Ticket.business_id == business_id,
        ~Ticket.status.in_(("resolved", "closed")),
        Ticket.sla_due_at.is_not(None),
        Ticket.sla_due_at >= now,
        Ticket.sla_due_at <= now + timedelta(hours=24),
    ).count()
    return {
        "period_days": int(days),
        "period_start": period_start,
        "usage": usage,
        "provider": {
            "failed_events": int(failed_events),
            "retrying_events": int(retrying_events),
            "circuits": provider_breaker_snapshot(),
        },
        "ai": {
            "calls": used.get("ai_calls", 0),
            "cost": used.get("ai_cost", 0),
            "rag_runs": len(rag_runs),
            "rag_errors": rag_errors,
            "tool_errors": int(tool_errors),
        },
        "sla": {
            "open_tickets": int(open_tickets),
            "overdue_tickets": int(overdue_tickets),
            "due_soon_tickets": int(due_soon_tickets),
        },
    }


def _count(db: Session, model, business_id: int, *conditions) -> int:
    query = db.query(func.count(model.id)).filter(model.business_id == business_id)
    if conditions:
        query = query.filter(*conditions)
    return int(query.scalar() or 0)


def _parse_date(value: str | None, name: str, *, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.strip()
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        if end_of_day and len(normalized) == 10:
            return datetime.combine(parsed.date(), time.max)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{name} không hợp lệ; dùng ISO-8601.") from exc


@router.get("/reports/commerce")
def commerce_report(
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    start_at: str | None = Query(default=None),
    end_at: str | None = Query(default=None),
    channel: str | None = Query(default=None, max_length=30),
    status: str | None = Query(default=None, max_length=30),
    assigned_user_id: int | None = Query(default=None, ge=1),
):
    """Tenant-scoped commerce KPIs and recent source records for drill-through."""
    business_id = tenant.business_id
    start = _parse_date(start_at, "start_at")
    end = _parse_date(end_at, "end_at", end_of_day=True)
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="start_at phải trước end_at.")
    channel = channel.strip().lower() if channel else None
    if channel == "shopee":
        raise HTTPException(status_code=422, detail="Kênh Shopee nằm ngoài phạm vi báo cáo này.")

    order_query = db.query(Order).outerjoin(
        Conversation,
        (Conversation.id == Order.conversation_id) & (Conversation.business_id == business_id),
    ).filter(
        Order.business_id == business_id,
        or_(Conversation.channel.is_(None), func.lower(Conversation.channel) != "shopee"),
    )
    if start:
        order_query = order_query.filter(Order.created_at >= start)
    if end:
        order_query = order_query.filter(Order.created_at <= end)
    if channel:
        order_query = order_query.filter(Conversation.channel == channel)
    if assigned_user_id is not None:
        order_query = order_query.filter(Conversation.assigned_user_id == assigned_user_id)
    if status:
        order_query = order_query.filter(Order.status == status.strip().lower())
    order_ids = order_query.with_entities(Order.id).statement
    order_status_rows = db.query(Order.status, func.count(Order.id)).filter(Order.id.in_(order_ids)).group_by(Order.status).all()
    revenue = db.query(func.coalesce(func.sum(Order.total_amount), Decimal("0.00"))).filter(
        Order.id.in_(order_ids), Order.status.in_(REVENUE_ORDER_STATUSES),
    ).scalar() or Decimal("0.00")
    order_sources = db.query(Order, Customer.name, Conversation.channel).join(
        Customer, (Customer.id == Order.customer_id) & (Customer.business_id == business_id),
    ).outerjoin(
        Conversation,
        (Conversation.id == Order.conversation_id) & (Conversation.business_id == business_id),
    ).filter(Order.id.in_(order_ids)).order_by(Order.created_at.desc(), Order.id.desc()).limit(30).all()

    appointment_query = db.query(Appointment).filter(Appointment.business_id == business_id)
    if start:
        appointment_query = appointment_query.filter(Appointment.starts_at >= start)
    if end:
        appointment_query = appointment_query.filter(Appointment.starts_at <= end)
    if assigned_user_id is not None:
        appointment_query = appointment_query.filter(Appointment.assigned_user_id == assigned_user_id)
    if channel:
        appointment_query = appointment_query.filter(db.query(Conversation.id).filter(
            Conversation.business_id == business_id,
            Conversation.customer_id == Appointment.customer_id,
            Conversation.channel == channel,
        ).exists())
    if status:
        appointment_query = appointment_query.filter(Appointment.status == status.strip().lower())
    appointment_ids = appointment_query.with_entities(Appointment.id).statement
    appointment_status_rows = db.query(Appointment.status, func.count(Appointment.id)).filter(
        Appointment.id.in_(appointment_ids),
    ).group_by(Appointment.status).all()
    appointment_channel = db.query(Conversation.channel).filter(
        Conversation.business_id == business_id,
        Conversation.customer_id == Appointment.customer_id,
        func.lower(Conversation.channel) != "shopee",
    ).order_by(Conversation.id.desc()).limit(1).scalar_subquery()
    appointment_sources = db.query(Appointment, Customer.name, AppointmentService.name, appointment_channel).join(
        Customer, (Customer.id == Appointment.customer_id) & (Customer.business_id == business_id),
    ).join(
        AppointmentService,
        (AppointmentService.id == Appointment.service_id) & (AppointmentService.business_id == business_id),
    ).filter(Appointment.id.in_(appointment_ids)).order_by(
        Appointment.starts_at.desc(), Appointment.id.desc(),
    ).limit(30).all()

    quote_query = db.query(CommercialQuote).filter(CommercialQuote.business_id == business_id)
    if start:
        quote_query = quote_query.filter(CommercialQuote.created_at >= start)
    if end:
        quote_query = quote_query.filter(CommercialQuote.created_at <= end)
    if channel:
        quote_query = quote_query.filter(db.query(Conversation.id).filter(
            Conversation.business_id == business_id,
            Conversation.customer_id == CommercialQuote.customer_id,
            Conversation.channel == channel,
        ).exists())
    if assigned_user_id is not None:
        quote_query = quote_query.filter(db.query(CommercialProject.id).filter(
            CommercialProject.business_id == business_id,
            CommercialProject.quote_id == CommercialQuote.id,
            CommercialProject.assigned_user_id == assigned_user_id,
        ).exists())
    if status:
        quote_query = quote_query.filter(CommercialQuote.status == status.strip().lower())
    quote_ids = quote_query.with_entities(CommercialQuote.id).statement
    quote_status_rows = db.query(CommercialQuote.status, func.count(CommercialQuote.id)).filter(
        CommercialQuote.id.in_(quote_ids),
    ).group_by(CommercialQuote.status).all()
    accepted_quote_value = db.query(func.coalesce(func.sum(CommercialQuote.total_amount), Decimal("0.00"))).filter(
        CommercialQuote.id.in_(quote_ids), CommercialQuote.status == "accepted",
    ).scalar() or Decimal("0.00")
    quote_channel = db.query(Conversation.channel).filter(
        Conversation.business_id == business_id,
        Conversation.customer_id == CommercialQuote.customer_id,
        func.lower(Conversation.channel) != "shopee",
    ).order_by(Conversation.id.desc()).limit(1).scalar_subquery()
    quote_sources = db.query(CommercialQuote, Customer.name, quote_channel).join(
        Customer, (Customer.id == CommercialQuote.customer_id) & (Customer.business_id == business_id),
    ).filter(CommercialQuote.id.in_(quote_ids)).order_by(
        CommercialQuote.created_at.desc(), CommercialQuote.id.desc(),
    ).limit(30).all()

    project_query = db.query(CommercialProject).filter(CommercialProject.business_id == business_id)
    if start:
        project_query = project_query.filter(CommercialProject.created_at >= start)
    if end:
        project_query = project_query.filter(CommercialProject.created_at <= end)
    if assigned_user_id is not None:
        project_query = project_query.filter(CommercialProject.assigned_user_id == assigned_user_id)
    if status:
        project_query = project_query.filter(CommercialProject.status == status.strip().lower())
    project_ids = project_query.with_entities(CommercialProject.id).statement
    project_status_rows = db.query(CommercialProject.status, func.count(CommercialProject.id)).filter(
        CommercialProject.id.in_(project_ids),
    ).group_by(CommercialProject.status).all()

    invoice_query = db.query(CommercialInvoice).filter(CommercialInvoice.business_id == business_id)
    if start:
        invoice_query = invoice_query.filter(CommercialInvoice.created_at >= start)
    if end:
        invoice_query = invoice_query.filter(CommercialInvoice.created_at <= end)
    if channel:
        invoice_query = invoice_query.filter(db.query(Conversation.id).filter(
            Conversation.business_id == business_id,
            Conversation.customer_id == CommercialInvoice.customer_id,
            Conversation.channel == channel,
        ).exists())
    if assigned_user_id is not None:
        invoice_query = invoice_query.filter(db.query(CommercialProject.id).filter(
            CommercialProject.business_id == business_id,
            CommercialProject.id == CommercialInvoice.project_id,
            CommercialProject.assigned_user_id == assigned_user_id,
        ).exists())
    if status == "paid":
        invoice_query = invoice_query.filter(CommercialInvoice.paid_amount >= CommercialInvoice.total_amount)
    elif status == "overdue":
        invoice_query = invoice_query.filter(CommercialInvoice.status == "issued", CommercialInvoice.due_on < datetime.now(timezone.utc).date(), CommercialInvoice.paid_amount < CommercialInvoice.total_amount)
    elif status:
        invoice_query = invoice_query.filter(CommercialInvoice.status == status.strip().lower())
    invoice_ids = invoice_query.with_entities(CommercialInvoice.id).statement
    invoice_count = invoice_query.count()
    invoiced = db.query(func.coalesce(func.sum(CommercialInvoice.total_amount), Decimal("0.00"))).filter(
        CommercialInvoice.id.in_(invoice_ids), CommercialInvoice.status == "issued",
    ).scalar() or Decimal("0.00")
    collected = db.query(func.coalesce(func.sum(CommercialInvoice.paid_amount), Decimal("0.00"))).filter(
        CommercialInvoice.id.in_(invoice_ids), CommercialInvoice.status == "issued",
    ).scalar() or Decimal("0.00")
    invoice_channel = db.query(Conversation.channel).filter(
        Conversation.business_id == business_id,
        Conversation.customer_id == CommercialInvoice.customer_id,
        func.lower(Conversation.channel) != "shopee",
    ).order_by(Conversation.id.desc()).limit(1).scalar_subquery()
    invoice_sources = db.query(CommercialInvoice, Customer.name, invoice_channel).join(
        Customer, (Customer.id == CommercialInvoice.customer_id) & (Customer.business_id == business_id),
    ).filter(CommercialInvoice.id.in_(invoice_ids)).order_by(
        CommercialInvoice.created_at.desc(), CommercialInvoice.id.desc(),
    ).limit(30).all()

    sources = [
        {"kind": "order", "id": row.id, "label": row.order_number, "customer": name, "status": row.status, "amount": row.total_amount, "created_at": row.created_at, "channel": source_channel}
        for row, name, source_channel in order_sources
    ] + [
        {"kind": "appointment", "id": row.id, "label": f"{service_name} · {row.starts_at.isoformat()}", "customer": name, "status": row.status, "amount": None, "created_at": row.starts_at, "channel": source_channel}
        for row, name, service_name, source_channel in appointment_sources
    ] + [
        {"kind": "quote", "id": row.id, "label": row.quote_number, "customer": name, "status": row.status, "amount": row.total_amount, "created_at": row.created_at, "channel": source_channel}
        for row, name, source_channel in quote_sources
    ] + [
        {"kind": "invoice", "id": row.id, "label": row.invoice_number, "customer": name, "status": "void" if row.status == "void" else "paid" if row.paid_amount >= row.total_amount else "overdue" if row.status == "issued" and row.due_on is not None and row.due_on < datetime.now(timezone.utc).date() else row.status, "amount": row.total_amount, "created_at": row.created_at, "channel": source_channel}
        for row, name, source_channel in invoice_sources
    ]
    return {
        "definitions": {"revenue_statuses": list(REVENUE_ORDER_STATUSES), "orders_revenue": "sum of order totals in recognized sales states", "quote_value": "accepted quotes only", "invoice_outstanding": "issued invoice totals less recorded payments"},
        "orders": {"count": sum(int(count) for _, count in order_status_rows), "recognized_revenue": Decimal(revenue).quantize(Decimal("0.01")), "average_order_value": (Decimal(revenue) / sum(int(count) for stage, count in order_status_rows if stage in REVENUE_ORDER_STATUSES)).quantize(Decimal("0.01")) if sum(int(count) for stage, count in order_status_rows if stage in REVENUE_ORDER_STATUSES) else Decimal("0.00"), "by_status": {str(stage): int(count) for stage, count in order_status_rows}},
        "appointments": {"count": sum(int(count) for _, count in appointment_status_rows), "by_status": {str(stage): int(count) for stage, count in appointment_status_rows}},
        "quotes": {"count": sum(int(count) for _, count in quote_status_rows), "accepted_value": Decimal(accepted_quote_value).quantize(Decimal("0.01")), "by_status": {str(stage): int(count) for stage, count in quote_status_rows}},
        "projects": {"count": sum(int(count) for _, count in project_status_rows), "by_status": {str(stage): int(count) for stage, count in project_status_rows}},
        "invoices": {"count": invoice_count, "issued_total": Decimal(invoiced).quantize(Decimal("0.01")), "collected": Decimal(collected).quantize(Decimal("0.01")), "outstanding": Decimal(invoiced - collected).quantize(Decimal("0.01"))},
        "source_records": sources[:100],
    }


@router.get("/reports/overview", response_model=CrmOverviewOut)
def crm_overview(
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    start_at: str | None = Query(default=None),
    end_at: str | None = Query(default=None),
    channel: str | None = Query(default=None, max_length=30),
    status: str | None = Query(default=None, max_length=30),
    assigned_user_id: int | None = Query(default=None, ge=1),
):
    business_id = tenant.business_id
    start = _parse_date(start_at, "start_at")
    end = _parse_date(end_at, "end_at", end_of_day=True)
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="start_at phải trước end_at.")

    conversation_query = db.query(Conversation).filter(Conversation.business_id == business_id)
    if channel:
        conversation_query = conversation_query.filter(Conversation.channel == channel.strip().lower())
    if start:
        conversation_query = conversation_query.filter(Conversation.created_at >= start)
    if end:
        conversation_query = conversation_query.filter(Conversation.created_at <= end)
    if assigned_user_id is not None:
        conversation_query = conversation_query.filter(Conversation.assigned_user_id == assigned_user_id)
    conversation_ids = [row.id for row in conversation_query.with_entities(Conversation.id).all()]

    customer_query = db.query(Customer).filter(Customer.business_id == business_id)
    if conversation_ids:
        customer_query = customer_query.filter(Customer.id.in_(db.query(Conversation.customer_id).filter(Conversation.id.in_(conversation_ids))))
    elif channel or start or end or assigned_user_id is not None:
        customer_query = customer_query.filter(False)
    customer_count = customer_query.count()
    conversation_count = conversation_query.count()

    ticket_query = db.query(Ticket).filter(Ticket.business_id == business_id)
    lead_query = db.query(Lead).filter(Lead.business_id == business_id)
    order_query = db.query(Order).outerjoin(
        Conversation,
        (Conversation.id == Order.conversation_id) & (Conversation.business_id == business_id),
    ).filter(
        Order.business_id == business_id,
        or_(Conversation.channel.is_(None), func.lower(Conversation.channel) != "shopee"),
    )
    if start:
        ticket_query = ticket_query.filter(Ticket.created_at >= start)
        lead_query = lead_query.filter(Lead.created_at >= start)
        order_query = order_query.filter(Order.created_at >= start)
    if end:
        ticket_query = ticket_query.filter(Ticket.created_at <= end)
        lead_query = lead_query.filter(Lead.created_at <= end)
        order_query = order_query.filter(Order.created_at <= end)
    if status:
        ticket_query = ticket_query.filter(Ticket.status == status)
        order_query = order_query.filter(Order.status == status)
    if assigned_user_id is not None:
        ticket_query = ticket_query.filter(Ticket.assigned_user_id == assigned_user_id)
        lead_query = lead_query.filter(Lead.assigned_user_id == assigned_user_id)
    if channel:
        lead_query = lead_query.filter(Lead.source_channel == channel.strip().lower())
        order_query = order_query.filter(Conversation.channel == channel.strip().lower())
    ticket_count = ticket_query.count()
    open_ticket_count = ticket_query.filter(Ticket.status.not_in(("resolved", "closed"))).count()
    lead_count = lead_query.count()
    won_lead_count = lead_query.filter(Lead.stage == "won").count()
    order_count = order_query.count()
    revenue_order_query = order_query.filter(Order.status.in_(REVENUE_ORDER_STATUSES))
    total_revenue = Decimal("0.00")
    if revenue_order_query.count():
        total_revenue = db.query(func.coalesce(func.sum(Order.total_amount), Decimal("0.00"))).filter(
            Order.id.in_(revenue_order_query.with_entities(Order.id))
        ).scalar() or Decimal("0.00")

    # Keep the summary endpoint useful for dashboards without forcing each
    # client to run a second aggregation query.  All rows are already
    # constrained by the same tenant and filter set above.
    breakdown_rows = db.query(
        func.coalesce(Conversation.channel, "unknown").label("channel"),
        func.count(Order.id).label("order_count"),
        func.coalesce(func.sum(Order.total_amount), Decimal("0.00")).label("revenue"),
    ).outerjoin(
        Conversation,
        (Conversation.id == Order.conversation_id)
        & (Conversation.business_id == business_id),
    ).filter(Order.id.in_(revenue_order_query.with_entities(Order.id))).group_by(
        # Group by the source column, not a separately-bound COALESCE
        # expression.  PostgreSQL treats the different bind parameters as
        # distinct expressions and otherwise raises a GROUP BY error.
        Conversation.channel
    ).order_by(Conversation.channel).all() if revenue_order_query.count() else []
    channel_breakdown = [
        {"channel": str(row.channel), "order_count": int(row.order_count), "revenue": Decimal(row.revenue or 0).quantize(Decimal("0.01"))}
        for row in breakdown_rows
    ]
    series_map: dict[str, dict] = {}
    for conversation in conversation_query.all():
        key = conversation.created_at.date().isoformat() if conversation.created_at else "unknown"
        series_map.setdefault(key, {"date": key, "conversations": 0, "orders": 0, "revenue": Decimal("0.00")})["conversations"] += 1
    for order in order_query.all():
        key = order.created_at.date().isoformat() if order.created_at else "unknown"
        bucket = series_map.setdefault(key, {"date": key, "conversations": 0, "orders": 0, "revenue": Decimal("0.00")})
        bucket["orders"] += 1
        if order.status in REVENUE_ORDER_STATUSES:
            bucket["revenue"] += Decimal(order.total_amount or 0)
    time_series = sorted(series_map.values(), key=lambda item: item["date"])
    purchase_query = db.query(PurchaseOrder).filter(PurchaseOrder.business_id == business_id)
    if start:
        purchase_query = purchase_query.filter(PurchaseOrder.created_at >= start)
    if end:
        purchase_query = purchase_query.filter(PurchaseOrder.created_at <= end)
    if status:
        purchase_query = purchase_query.filter(PurchaseOrder.status == status.strip().lower())
    purchase_order_count = purchase_query.count()
    purchase_spend = purchase_query.with_entities(func.coalesce(func.sum(PurchaseOrder.total_spend), Decimal("0.00"))).scalar() or Decimal("0.00")

    conversion_rate = round((won_lead_count / lead_count) * 100, 2) if lead_count else 0.0
    conversation_to_order_rate = round((order_count / conversation_count) * 100, 2) if conversation_count else 0.0
    return CrmOverviewOut(
        customer_count=customer_count,
        conversation_count=conversation_count,
        ticket_count=ticket_count,
        open_ticket_count=open_ticket_count,
        lead_count=lead_count,
        won_lead_count=won_lead_count,
        order_count=order_count,
        total_revenue=Decimal(total_revenue).quantize(Decimal("0.01")),
        conversion_rate=conversion_rate,
        conversation_to_order_rate=conversation_to_order_rate,
        channel_breakdown=channel_breakdown,
        time_series=time_series,
        purchase_order_count=purchase_order_count,
        purchase_spend=Decimal(purchase_spend).quantize(Decimal("0.01")),
    )


@router.get("/reports/overview.csv")
def crm_overview_csv(
    db: Session = Depends(get_tenant_db),
    platform_db: Session = Depends(get_platform_db),
    tenant: TenantContext = Depends(get_tenant_context),
    start_at: str | None = Query(default=None),
    end_at: str | None = Query(default=None),
    channel: str | None = Query(default=None, max_length=30),
    status: str | None = Query(default=None, max_length=30),
    assigned_user_id: int | None = Query(default=None, ge=1),
):
    """Export the headline CRM metrics in a spreadsheet-friendly format."""
    overview = crm_overview(
        db=db,
        platform_db=platform_db,
        tenant=tenant,
        start_at=start_at,
        end_at=end_at,
        channel=channel,
        status=status,
        assigned_user_id=assigned_user_id,
    )
    business_id = tenant.business_id
    purchase_query = db.query(PurchaseOrder).filter(PurchaseOrder.business_id == business_id)
    if start_at:
        purchase_query = purchase_query.filter(PurchaseOrder.created_at >= _parse_date(start_at, "start_at"))
    if end_at:
        purchase_query = purchase_query.filter(PurchaseOrder.created_at <= _parse_date(end_at, "end_at", end_of_day=True))
    if status:
        purchase_query = purchase_query.filter(PurchaseOrder.status == status.strip().lower())
    rows = [
        ("customers", overview.customer_count),
        ("conversations", overview.conversation_count),
        ("tickets", overview.ticket_count),
        ("leads", overview.lead_count),
        ("sales_orders", overview.order_count),
        ("sales_revenue", overview.total_revenue),
        ("purchase_orders", purchase_query.count()),
        ("purchase_spend", purchase_query.with_entities(func.coalesce(func.sum(PurchaseOrder.total_spend), Decimal("0"))).scalar() or Decimal("0")),
    ]
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["metric", "value"])
    writer.writerows(rows)
    return Response(content=output.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=crm-overview.csv"})


@router.get("/reports/spend-by-supplier")
def spend_by_supplier(db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context)):
    rows = db.query(
        PurchaseOrder.supplier_name,
        func.count(PurchaseOrder.id).label("order_count"),
        func.coalesce(func.sum(PurchaseOrder.total_spend), Decimal("0")).label("spend"),
    ).filter(PurchaseOrder.business_id == tenant.business_id).group_by(PurchaseOrder.supplier_name).order_by(PurchaseOrder.supplier_name.asc()).all()
    return {"items": [{"supplier_name": row.supplier_name, "order_count": int(row.order_count), "spend": Decimal(row.spend or 0)} for row in rows], "total_spend": sum((Decimal(row.spend or 0) for row in rows), Decimal("0"))}


@router.get("/reports/inventory")
def inventory_report(db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context)):
    """Return on-hand, reserved and ledger totals for every tenant product."""
    products = db.query(Product).filter(Product.business_id == tenant.business_id).order_by(Product.name.asc(), Product.id.asc()).all()
    movement_rows = db.query(
        StockMovement.product_id,
        func.coalesce(func.sum(StockMovement.quantity), 0).label("net_quantity"),
        func.count(StockMovement.id).label("movement_count"),
    ).filter(StockMovement.business_id == tenant.business_id).group_by(StockMovement.product_id).all()
    movement_map = {row.product_id: row for row in movement_rows}
    items = []
    for product in products:
        row = movement_map.get(product.id)
        stock = int(product.stock_quantity or 0)
        reserved = int(product.reserved_quantity or 0)
        items.append({
            "product_id": product.id,
            "sku": product.sku,
            "name": product.name,
            "stock_quantity": stock,
            "reserved_quantity": reserved,
            "available_quantity": stock - reserved,
            "net_movement_quantity": int(row.net_quantity or 0) if row else 0,
            "movement_count": int(row.movement_count or 0) if row else 0,
        })
    return {
        "items": items,
        "total": len(items),
        "stock_quantity": sum(item["stock_quantity"] for item in items),
        "reserved_quantity": sum(item["reserved_quantity"] for item in items),
        "available_quantity": sum(item["available_quantity"] for item in items),
    }


@router.get("/reports/purchase-costs")
def purchase_cost_report(
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    start_at: str | None = Query(default=None),
    end_at: str | None = Query(default=None),
):
    """Aggregate received inventory cost by supplier and receipt date."""
    start = _parse_date(start_at, "start_at")
    end = _parse_date(end_at, "end_at", end_of_day=True)
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="start_at phải trước end_at.")
    rows = db.query(PurchaseReceiptItem, PurchaseReceipt, PurchaseOrderItem, PurchaseOrder).join(
        PurchaseReceipt, PurchaseReceipt.id == PurchaseReceiptItem.receipt_id,
    ).join(
        PurchaseOrderItem, PurchaseOrderItem.id == PurchaseReceiptItem.purchase_order_item_id,
    ).join(
        PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id,
    ).filter(
        PurchaseReceipt.business_id == tenant.business_id,
        PurchaseOrder.business_id == tenant.business_id,
    )
    if start:
        rows = rows.filter(PurchaseReceipt.received_at >= start)
    if end:
        rows = rows.filter(PurchaseReceipt.received_at <= end)
    grouped: dict[str, dict] = {}
    for receipt_item, receipt, po_item, purchase in rows.all():
        supplier_name = purchase.supplier_name_snapshot or purchase.supplier_name
        bucket = grouped.setdefault(supplier_name, {"supplier_name": supplier_name, "receipt_count": set(), "received_quantity": 0, "received_cost": Decimal("0")})
        bucket["receipt_count"].add(receipt.id)
        bucket["received_quantity"] += int(receipt_item.quantity or 0)
        bucket["received_cost"] += Decimal(receipt_item.quantity or 0) * Decimal(po_item.unit_cost or 0)
    items = []
    for bucket in sorted(grouped.values(), key=lambda value: value["supplier_name"]):
        items.append({
            "supplier_name": bucket["supplier_name"],
            "receipt_count": len(bucket["receipt_count"]),
            "received_quantity": bucket["received_quantity"],
            "received_cost": bucket["received_cost"],
        })
    return {"items": items, "total_received_cost": sum((item["received_cost"] for item in items), Decimal("0"))}


@router.get("/reports/agent-performance", response_model=AgentPerformanceOut)
def agent_performance(
    db: Session = Depends(get_tenant_db),
    platform_db: Session = Depends(get_platform_db),
    user_db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    business_id = tenant.business_id
    # Newer control-plane installs may expose platform_users, while the
    # current login/team contract still stores shop staff in the legacy users
    # table. Prefer the control-plane query when it is available and fall back
    # to the authenticated shop database so reports never fail just because a
    # deployment is mid-migration. (The compatibility query remains
    # ``platform_db.query(User)`` for older test fixtures.)
    try:
        users = platform_db.query(User).filter(User.business_id == business_id).order_by(User.full_name.asc(), User.id.asc()).all()
    except Exception:  # noqa: BLE001 - schema rollout fallback
        platform_db.rollback()
        users = user_db.query(User).filter(User.business_id == business_id).order_by(User.full_name.asc(), User.id.asc()).all()
    items: list[AgentPerformanceItem] = []
    for user in users:
        assigned_conversations = int(db.query(func.count(Conversation.id)).filter(
            Conversation.business_id == business_id,
            Conversation.assigned_user_id == user.id,
        ).scalar() or 0)
        assigned_tickets = int(db.query(func.count(Ticket.id)).filter(
            Ticket.business_id == business_id,
            Ticket.assigned_user_id == user.id,
        ).scalar() or 0)
        resolved_tickets = int(db.query(func.count(Ticket.id)).filter(
            Ticket.business_id == business_id,
            Ticket.assigned_user_id == user.id,
            Ticket.status.in_(("resolved", "closed")),
        ).scalar() or 0)
        assigned_leads = int(db.query(func.count(Lead.id)).filter(
            Lead.business_id == business_id,
            Lead.assigned_user_id == user.id,
        ).scalar() or 0)
        won_leads = int(db.query(func.count(Lead.id)).filter(
            Lead.business_id == business_id,
            Lead.assigned_user_id == user.id,
            Lead.stage == "won",
        ).scalar() or 0)
        items.append(AgentPerformanceItem(
            user_id=user.id,
            full_name=user.full_name,
            role=user.role,
            assigned_conversations=assigned_conversations,
            assigned_tickets=assigned_tickets,
            resolved_tickets=resolved_tickets,
            assigned_leads=assigned_leads,
            won_leads=won_leads,
        ))
    return AgentPerformanceOut(items=items)
