"""Tenant-scoped revenue touchpoints and attribution APIs."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.auth.dependencies import require_write_access
from app.db.dependencies import get_db
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.lead import Lead
from app.models.revenue import RevenueAttribution, RevenueTouchpoint
from app.models.sales import Order
from app.schemas.revenue import AttributionOut, AttributionRequest, TouchpointCreate, TouchpointListOut, TouchpointOut
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context


router = APIRouter()
SUPPORTED_MODELS = {"first_touch", "last_touch", "linear", "time_decay", "manual"}


def _touchpoint(db: Session, touchpoint_id: int, tenant: TenantContext) -> RevenueTouchpoint:
    row = db.query(RevenueTouchpoint).filter(RevenueTouchpoint.id == touchpoint_id, RevenueTouchpoint.business_id == tenant.business_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Touchpoint không tồn tại.")
    return row


@router.post("/revenue/touchpoints", response_model=TouchpointOut, status_code=201, dependencies=[Depends(require_write_access)])
def create_touchpoint(payload: TouchpointCreate, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    if payload.customer_id is not None and db.query(Customer.id).filter(Customer.id == payload.customer_id, Customer.business_id == tenant.business_id).first() is None:
        raise HTTPException(status_code=404, detail="Customer không thuộc business này.")
    if payload.conversation_id is not None:
        conversation = db.query(Conversation).filter(Conversation.id == payload.conversation_id, Conversation.business_id == tenant.business_id).first()
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation không thuộc business này.")
        if payload.customer_id is not None and conversation.customer_id != payload.customer_id:
            raise HTTPException(status_code=422, detail="Conversation không thuộc customer này.")
    if payload.lead_id is not None and db.query(Lead.id).filter(Lead.id == payload.lead_id, Lead.business_id == tenant.business_id).first() is None:
        raise HTTPException(status_code=404, detail="Lead không thuộc business này.")
    row = RevenueTouchpoint(
        business_id=tenant.business_id,
        customer_id=payload.customer_id,
        conversation_id=payload.conversation_id,
        lead_id=payload.lead_id,
        channel=payload.channel.strip().lower() if payload.channel else None,
        source=payload.source.strip(),
        campaign=payload.campaign.strip() if payload.campaign else None,
        occurred_at=payload.occurred_at or datetime.now(timezone.utc).replace(tzinfo=None),
        metadata_=payload.metadata,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/revenue/touchpoints", response_model=TouchpointListOut)
def list_touchpoints(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    customer_id: int | None = Query(default=None, ge=1),
    lead_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    query = db.query(RevenueTouchpoint).filter(RevenueTouchpoint.business_id == tenant.business_id)
    if customer_id is not None:
        query = query.filter(RevenueTouchpoint.customer_id == customer_id)
    if lead_id is not None:
        query = query.filter(RevenueTouchpoint.lead_id == lead_id)
    total = query.count()
    rows = query.order_by(RevenueTouchpoint.occurred_at.asc(), RevenueTouchpoint.id.asc()).offset(offset).limit(limit).all()
    return TouchpointListOut(items=rows, total=total)


@router.post("/orders/{order_id}/attribution", response_model=AttributionOut, dependencies=[Depends(require_write_access)])
def recalculate_attribution(
    order_id: int,
    payload: AttributionRequest,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    order = db.query(Order).filter(Order.id == order_id, Order.business_id == tenant.business_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Đơn hàng không tồn tại.")
    if payload.model not in SUPPORTED_MODELS:
        raise HTTPException(status_code=422, detail="Attribution model không hợp lệ.")
    touchpoints = db.query(RevenueTouchpoint).filter(
        RevenueTouchpoint.business_id == tenant.business_id,
        RevenueTouchpoint.customer_id == order.customer_id,
    ).order_by(RevenueTouchpoint.occurred_at.asc(), RevenueTouchpoint.id.asc()).all()
    if not touchpoints and order.conversation_id is not None:
        conversation = db.query(Conversation).filter(Conversation.id == order.conversation_id, Conversation.business_id == tenant.business_id).first()
        if conversation is not None:
            touchpoints = [RevenueTouchpoint(
                business_id=tenant.business_id,
                customer_id=order.customer_id,
                conversation_id=conversation.id,
                channel=conversation.channel,
                source="conversation",
                occurred_at=conversation.created_at or datetime.now(timezone.utc).replace(tzinfo=None),
            )]
            db.add(touchpoints[0])
            db.flush()
    if not touchpoints:
        raise HTTPException(status_code=422, detail="Chưa có touchpoint để phân bổ doanh thu.")
    if payload.model == "first_touch":
        weights = [Decimal("1") if index == 0 else Decimal("0") for index in range(len(touchpoints))]
    elif payload.model == "last_touch":
        weights = [Decimal("1") if index == len(touchpoints) - 1 else Decimal("0") for index in range(len(touchpoints))]
    elif payload.model == "time_decay":
        raw = [Decimal(index + 1) for index in range(len(touchpoints))]
        total = sum(raw, Decimal("0"))
        weights = [value / total for value in raw]
    else:
        weights = [Decimal("1") / Decimal(len(touchpoints)) for _ in touchpoints]
    db.execute(delete(RevenueAttribution).where(
        RevenueAttribution.business_id == tenant.business_id,
        RevenueAttribution.order_id == order.id,
        RevenueAttribution.model == payload.model,
    ))
    # The allocation table stores currency at two decimal places.  Rounding
    # each individual share independently can otherwise leave a one-cent gap
    # (for example, 100 / 3 becomes 33.33 * 3 = 99.99).  Keep the final
    # allocation as the exact remainder so every recalculation reconciles to
    # the order total.
    total_amount = Decimal(order.total_amount or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    items = []
    allocated = Decimal("0.00")
    for index, (touchpoint, weight) in enumerate(zip(touchpoints, weights)):
        if index == len(touchpoints) - 1:
            amount = total_amount - allocated
        else:
            amount = (total_amount * weight).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            allocated += amount
        db.add(RevenueAttribution(
            business_id=tenant.business_id,
            order_id=order.id,
            touchpoint_id=touchpoint.id,
            model=payload.model,
            weight=weight,
            amount=amount,
        ))
        items.append({"touchpoint_id": touchpoint.id, "source": touchpoint.source, "channel": touchpoint.channel, "campaign": touchpoint.campaign, "weight": weight, "amount": amount})
    db.commit()
    return AttributionOut(order_id=order.id, model=payload.model, total_attributed=sum((item["amount"] for item in items), Decimal("0")), items=items)


@router.get("/reports/revenue-attribution")
def revenue_attribution_report(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    model: str = Query(default="last_touch"),
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    channel: str | None = None,
    source: str | None = None,
    campaign: str | None = None,
):
    if model not in SUPPORTED_MODELS:
        raise HTTPException(status_code=422, detail="Attribution model không hợp lệ.")
    if start_at is not None and end_at is not None and end_at < start_at:
        raise HTTPException(status_code=422, detail="Khoảng thời gian báo cáo không hợp lệ.")
    query = db.query(RevenueTouchpoint.channel, RevenueTouchpoint.source, RevenueTouchpoint.campaign, RevenueAttribution.amount).join(
        RevenueAttribution,
        (RevenueAttribution.touchpoint_id == RevenueTouchpoint.id) & (RevenueAttribution.business_id == tenant.business_id),
    ).filter(RevenueTouchpoint.business_id == tenant.business_id, RevenueAttribution.model == model)
    if start_at is not None:
        query = query.filter(RevenueTouchpoint.occurred_at >= start_at)
    if end_at is not None:
        query = query.filter(RevenueTouchpoint.occurred_at <= end_at)
    if channel:
        query = query.filter(RevenueTouchpoint.channel == channel.strip().lower())
    if source:
        query = query.filter(RevenueTouchpoint.source == source.strip())
    if campaign:
        query = query.filter(RevenueTouchpoint.campaign == campaign.strip())
    rows = query.all()
    grouped: dict[tuple[str, str, str | None], Decimal] = {}
    for channel, source, campaign, amount in rows:
        key = (str(channel or "unknown"), str(source), campaign)
        grouped[key] = grouped.get(key, Decimal("0")) + Decimal(amount or 0)
    items = [{"channel": channel, "source": source, "campaign": campaign, "attributed_revenue": amount} for (channel, source, campaign), amount in sorted(grouped.items())]
    return {"model": model, "items": items, "total_attributed": sum((item["attributed_revenue"] for item in items), Decimal("0"))}
