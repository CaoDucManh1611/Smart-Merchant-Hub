"""Tenant-scoped CRM reporting endpoints."""

import csv
from datetime import datetime
from decimal import Decimal
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.models.business import User
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.lead import Lead
from app.models.sales import Order, Product
from app.models.ticket import Ticket
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order import PurchaseOrderItem
from app.models.inventory import PurchaseReceipt, PurchaseReceiptItem, StockMovement
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context


router = APIRouter()


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


def _count(db: Session, model, business_id: int, *conditions) -> int:
    query = db.query(func.count(model.id)).filter(model.business_id == business_id)
    if conditions:
        query = query.filter(*conditions)
    return int(query.scalar() or 0)


def _parse_date(value: str | None, name: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{name} không hợp lệ; dùng ISO-8601.") from exc


@router.get("/reports/overview", response_model=CrmOverviewOut)
def crm_overview(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    start_at: str | None = Query(default=None),
    end_at: str | None = Query(default=None),
    channel: str | None = Query(default=None, max_length=30),
    status: str | None = Query(default=None, max_length=30),
    assigned_user_id: int | None = Query(default=None, ge=1),
):
    business_id = tenant.business_id
    start = _parse_date(start_at, "start_at")
    end = _parse_date(end_at, "end_at")
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
    order_query = db.query(Order).filter(Order.business_id == business_id)
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
        order_query = order_query.join(Conversation, Conversation.id == Order.conversation_id).filter(Conversation.channel == channel.strip().lower())
    ticket_count = ticket_query.count()
    open_ticket_count = ticket_query.filter(Ticket.status.not_in(("resolved", "closed"))).count()
    lead_count = lead_query.count()
    won_lead_count = lead_query.filter(Lead.stage == "won").count()
    order_count = order_query.count()
    total_revenue = Decimal("0")
    if order_count:
        total_revenue = db.query(func.coalesce(func.sum(Order.total_amount), Decimal("0"))).filter(
            Order.id.in_(order_query.with_entities(Order.id))
        ).scalar() or Decimal("0")

    # Keep the summary endpoint useful for dashboards without forcing each
    # client to run a second aggregation query.  All rows are already
    # constrained by the same tenant and filter set above.
    breakdown_rows = db.query(
        func.coalesce(Conversation.channel, "unknown").label("channel"),
        func.count(Order.id).label("order_count"),
        func.coalesce(func.sum(Order.total_amount), Decimal("0")).label("revenue"),
    ).outerjoin(
        Conversation,
        (Conversation.id == Order.conversation_id)
        & (Conversation.business_id == business_id),
    ).filter(Order.id.in_(order_query.with_entities(Order.id))).group_by(
        # Group by the source column, not a separately-bound COALESCE
        # expression.  PostgreSQL treats the different bind parameters as
        # distinct expressions and otherwise raises a GROUP BY error.
        Conversation.channel
    ).order_by(Conversation.channel).all() if order_count else []
    channel_breakdown = [
        {"channel": str(row.channel), "order_count": int(row.order_count), "revenue": Decimal(row.revenue or 0)}
        for row in breakdown_rows
    ]
    series_map: dict[str, dict] = {}
    for conversation in conversation_query.all():
        key = conversation.created_at.date().isoformat() if conversation.created_at else "unknown"
        series_map.setdefault(key, {"date": key, "conversations": 0, "orders": 0, "revenue": Decimal("0")})["conversations"] += 1
    for order in order_query.all():
        key = order.created_at.date().isoformat() if order.created_at else "unknown"
        bucket = series_map.setdefault(key, {"date": key, "conversations": 0, "orders": 0, "revenue": Decimal("0")})
        bucket["orders"] += 1
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
    purchase_spend = purchase_query.with_entities(func.coalesce(func.sum(PurchaseOrder.total_spend), Decimal("0"))).scalar() or Decimal("0")

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
        total_revenue=Decimal(total_revenue),
        conversion_rate=conversion_rate,
        conversation_to_order_rate=conversation_to_order_rate,
        channel_breakdown=channel_breakdown,
        time_series=time_series,
        purchase_order_count=purchase_order_count,
        purchase_spend=Decimal(purchase_spend),
    )


@router.get("/reports/overview.csv")
def crm_overview_csv(
    db: Session = Depends(get_db),
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
        purchase_query = purchase_query.filter(PurchaseOrder.created_at <= _parse_date(end_at, "end_at"))
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
def spend_by_supplier(db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    rows = db.query(
        PurchaseOrder.supplier_name,
        func.count(PurchaseOrder.id).label("order_count"),
        func.coalesce(func.sum(PurchaseOrder.total_spend), Decimal("0")).label("spend"),
    ).filter(PurchaseOrder.business_id == tenant.business_id).group_by(PurchaseOrder.supplier_name).order_by(PurchaseOrder.supplier_name.asc()).all()
    return {"items": [{"supplier_name": row.supplier_name, "order_count": int(row.order_count), "spend": Decimal(row.spend or 0)} for row in rows], "total_spend": sum((Decimal(row.spend or 0) for row in rows), Decimal("0"))}


@router.get("/reports/inventory")
def inventory_report(db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
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
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    start_at: str | None = Query(default=None),
    end_at: str | None = Query(default=None),
):
    """Aggregate received inventory cost by supplier and receipt date."""
    start = _parse_date(start_at, "start_at")
    end = _parse_date(end_at, "end_at")
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
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    business_id = tenant.business_id
    users = db.query(User).filter(User.business_id == business_id).order_by(User.full_name.asc(), User.id.asc()).all()
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
