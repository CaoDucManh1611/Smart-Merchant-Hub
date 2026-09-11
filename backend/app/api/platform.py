"""Tenant-independent platform administration APIs."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.platform import require_platform_admin
from app.db.dependencies import get_db
from app.models.audit_log import AuditLog
from app.models.business import Business, Payment, ServicePlan, Subscription, User
from app.models.saas import SaaSUsage
from app.schemas.platform import (
    PlatformAuditOut,
    PlatformShopListOut,
    PlatformShopOut,
    PlatformStatusOut,
    PlatformStatusUpdate,
    PlatformUsageOut,
    TenantSchemaListOut,
    TenantSchemaOut,
    TenantSchemaUpdate,
    PlatformPlanCreate,
    PlatformPlanOut,
    PlatformSubscriptionOut,
    PlatformSubscriptionUpdate,
    PlatformPaymentCreate,
    PlatformPaymentOut,
)
from app.services.audit_service import record_audit
from app.services.quota_service import PLAN_LIMIT_FIELDS, quota_period_start
from app.services.tenant_schema_service import ensure_registry, update_registry


router = APIRouter(prefix="/platform")


def _number(value):
    if value is None:
        return None
    integer = int(value)
    return integer if value == integer else float(value)


def _plan_for(db: Session, business_id: int) -> ServicePlan | None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return db.scalar(
        select(ServicePlan)
        .join(Subscription, Subscription.plan_id == ServicePlan.id)
        .where(
            Subscription.business_id == business_id,
            Subscription.status == "active",
            (Subscription.starts_at.is_(None) | (Subscription.starts_at <= now)),
            (Subscription.ends_at.is_(None) | (Subscription.ends_at > now)),
        )
        .order_by(Subscription.id.desc())
    )


def _usage_for(db: Session, business_id: int, period_start):
    rows = db.scalars(
        select(SaaSUsage).where(
            SaaSUsage.business_id == business_id,
            SaaSUsage.period_start == period_start,
        )
    ).all()
    return {row.resource: _number(row.used or 0) for row in rows}


def _shop_out(db: Session, business: Business, period_start) -> PlatformShopOut:
    plan = _plan_for(db, business.id)
    return PlatformShopOut(
        id=business.id,
        name=business.name,
        slug=business.slug,
        status=business.status,
        plan_code=plan.code if plan else None,
        plan_name=plan.name if plan else None,
        usage=_usage_for(db, business.id, period_start),
        period_start=period_start,
    )


def _subscription_out(row: Subscription) -> PlatformSubscriptionOut:
    return PlatformSubscriptionOut(
        id=row.id,
        business_id=row.business_id,
        plan_id=row.plan_id,
        plan_code=row.plan.code,
        plan_name=row.plan.name,
        status=row.status,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        auto_renew=row.auto_renew,
        created_at=row.created_at,
    )


def _payment_out(row: Payment) -> PlatformPaymentOut:
    return PlatformPaymentOut(
        id=row.id,
        business_id=row.business_id,
        subscription_id=row.subscription_id,
        amount=row.amount,
        currency=row.currency,
        provider=row.provider,
        provider_transaction_id=row.provider_transaction_id,
        status=row.status,
        paid_at=row.paid_at,
        created_at=row.created_at,
    )


@router.get("/plans", response_model=list[PlatformPlanOut])
def list_plans(
    db: Session = Depends(get_db),
    _actor: User = Depends(require_platform_admin),
):
    return db.scalars(select(ServicePlan).order_by(ServicePlan.status.asc(), ServicePlan.id.asc())).all()


@router.post("/plans", response_model=PlatformPlanOut, status_code=201)
def create_plan(
    payload: PlatformPlanCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_platform_admin),
):
    plan = ServicePlan(**payload.model_dump())
    db.add(plan)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Mã gói dịch vụ đã tồn tại.") from exc
    record_audit(
        db,
        business_id=actor.business_id,
        user_id=actor.id,
        action="platform_plan_created",
        resource_type="service_plan",
        resource_id=plan.id,
        metadata={"code": plan.code, "status": plan.status},
    )
    db.commit()
    db.refresh(plan)
    return plan


@router.patch("/plans/{plan_id}", response_model=PlatformPlanOut)
def update_plan(
    plan_id: int,
    payload: PlatformPlanCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_platform_admin),
):
    plan = db.get(ServicePlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Gói dịch vụ không tồn tại.")
    for field, value in payload.model_dump().items():
        setattr(plan, field, value)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Mã gói dịch vụ đã tồn tại.") from exc
    record_audit(
        db,
        business_id=actor.business_id,
        user_id=actor.id,
        action="platform_plan_updated",
        resource_type="service_plan",
        resource_id=plan.id,
        metadata={"code": plan.code, "status": plan.status},
    )
    db.commit()
    db.refresh(plan)
    return plan


@router.get("/shops", response_model=PlatformShopListOut)
def list_shops(
    db: Session = Depends(get_db),
    _actor: User = Depends(require_platform_admin),
):
    period_start = quota_period_start()
    shops = db.scalars(select(Business).order_by(Business.id.asc())).all()
    return PlatformShopListOut(
        items=[_shop_out(db, shop, period_start) for shop in shops],
        total=len(shops),
    )


@router.get("/shops/{business_id}/subscription", response_model=PlatformSubscriptionOut)
def get_shop_subscription(
    business_id: int,
    db: Session = Depends(get_db),
    _actor: User = Depends(require_platform_admin),
):
    if db.get(Business, business_id) is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    row = db.scalar(
        select(Subscription)
        .where(Subscription.business_id == business_id)
        .order_by(Subscription.id.desc())
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Shop chưa có gói dịch vụ.")
    return _subscription_out(row)


@router.put("/shops/{business_id}/subscription", response_model=PlatformSubscriptionOut)
def upsert_shop_subscription(
    business_id: int,
    payload: PlatformSubscriptionUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_platform_admin),
):
    if db.get(Business, business_id) is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    plan = db.get(ServicePlan, payload.plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Gói dịch vụ không tồn tại.")
    if payload.status == "active" and plan.status != "active":
        raise HTTPException(status_code=409, detail="Không thể kích hoạt gói đã lưu trữ.")
    row = db.scalar(
        select(Subscription)
        .where(Subscription.business_id == business_id)
        .order_by(Subscription.id.desc())
    )
    if row is None:
        row = Subscription(business_id=business_id)
        db.add(row)
    elif row.status == "active" and row.plan_id != plan.id:
        row.status = "cancelled"
        row = Subscription(business_id=business_id)
        db.add(row)
    row.plan_id = plan.id
    row.status = payload.status
    row.starts_at = payload.starts_at
    row.ends_at = payload.ends_at
    row.auto_renew = payload.auto_renew
    db.flush()
    record_audit(
        db,
        business_id=business_id,
        user_id=actor.id,
        action="platform_subscription_updated",
        resource_type="subscription",
        resource_id=row.id,
        metadata={"plan_code": plan.code, "status": row.status, "auto_renew": row.auto_renew},
    )
    db.commit()
    db.refresh(row)
    return _subscription_out(row)


@router.get("/shops/{business_id}/payments", response_model=list[PlatformPaymentOut])
def list_shop_payments(
    business_id: int,
    db: Session = Depends(get_db),
    _actor: User = Depends(require_platform_admin),
):
    if db.get(Business, business_id) is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    return db.scalars(
        select(Payment)
        .where(Payment.business_id == business_id)
        .order_by(Payment.created_at.desc(), Payment.id.desc())
    ).all()


@router.post("/shops/{business_id}/payments", response_model=PlatformPaymentOut, status_code=201)
def record_shop_payment(
    business_id: int,
    payload: PlatformPaymentCreate,
    response: Response,
    db: Session = Depends(get_db),
    actor: User = Depends(require_platform_admin),
):
    if db.get(Business, business_id) is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    subscription = db.scalar(
        select(Subscription).where(
            Subscription.id == payload.subscription_id,
            Subscription.business_id == business_id,
        )
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription không thuộc shop.")
    existing = db.scalar(
        select(Payment).where(Payment.provider_transaction_id == payload.provider_transaction_id)
    )
    if existing is not None:
        if existing.business_id != business_id:
            raise HTTPException(status_code=409, detail="Mã giao dịch đã thuộc shop khác.")
        response.status_code = 200
        return existing
    payment = Payment(
        business_id=business_id,
        subscription_id=subscription.id,
        amount=payload.amount,
        currency=payload.currency.upper(),
        provider=payload.provider.strip().lower(),
        provider_transaction_id=payload.provider_transaction_id.strip(),
        status=payload.status,
        paid_at=payload.paid_at,
    )
    if payment.status == "paid" and payment.paid_at is None:
        payment.paid_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(payment)
    if payment.status == "paid" and subscription.status == "pending":
        subscription.status = "active"
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(select(Payment).where(Payment.provider_transaction_id == payload.provider_transaction_id))
        if existing is None or existing.business_id != business_id:
            raise HTTPException(status_code=409, detail="Mã giao dịch đã tồn tại.") from exc
        response.status_code = 200
        return existing
    record_audit(
        db,
        business_id=business_id,
        user_id=actor.id,
        action="platform_payment_recorded",
        resource_type="subscription_payment",
        resource_id=payment.id,
        metadata={"subscription_id": subscription.id, "amount": str(payment.amount), "status": payment.status, "provider": payment.provider},
    )
    db.commit()
    db.refresh(payment)
    return payment


@router.patch("/shops/{business_id}/status", response_model=PlatformStatusOut)
def update_shop_status(
    business_id: int,
    payload: PlatformStatusUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_platform_admin),
):
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    previous = business.status
    business.status = payload.status
    record_audit(
        db,
        business_id=business.id,
        user_id=actor.id,
        action="platform_status_changed",
        resource_type="business",
        resource_id=business.id,
        metadata={"from": previous, "to": business.status},
    )
    db.commit()
    db.refresh(business)
    return PlatformStatusOut(id=business.id, status=business.status, updated_at=business.updated_at)


@router.get("/shops/{business_id}/usage", response_model=PlatformUsageOut)
def get_shop_usage(
    business_id: int,
    db: Session = Depends(get_db),
    _actor: User = Depends(require_platform_admin),
):
    if db.get(Business, business_id) is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    plan = _plan_for(db, business_id)
    limits = {
        resource: _number(getattr(plan, field)) if plan else None
        for resource, field in PLAN_LIMIT_FIELDS.items()
    }
    period_start = quota_period_start()
    return PlatformUsageOut(
        business_id=business_id,
        period_start=period_start,
        plan_code=plan.code if plan else None,
        limits=limits,
        usage=_usage_for(db, business_id, period_start),
    )


@router.get("/audit-logs", response_model=list[PlatformAuditOut])
def list_platform_audit_logs(
    db: Session = Depends(get_db),
    _actor: User = Depends(require_platform_admin),
    limit: int = Query(default=100, ge=1, le=500),
):
    return db.scalars(
        select(AuditLog)
        .where(AuditLog.action.like("platform_%"))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
    ).all()


@router.get("/events", response_model=list[PlatformAuditOut])
def list_unified_events(
    db: Session = Depends(get_db),
    _actor: User = Depends(require_platform_admin),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Read the canonical event stream used by audit and Customer 360."""
    return db.scalars(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
    ).all()


@router.get("/tenant-schemas", response_model=TenantSchemaListOut)
def list_tenant_schemas(
    db: Session = Depends(get_db),
    _actor: User = Depends(require_platform_admin),
):
    from app.models.saas import TenantSchemaRegistry

    rows = db.scalars(
        select(TenantSchemaRegistry).order_by(TenantSchemaRegistry.business_id.asc())
    ).all()
    return TenantSchemaListOut(items=rows, total=len(rows))


@router.post("/tenant-schemas/{business_id}", response_model=TenantSchemaOut)
def register_tenant_schema(
    business_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_platform_admin),
):
    try:
        row = ensure_registry(db, business_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    record_audit(
        db,
        business_id=business_id,
        user_id=actor.id,
        action="platform_tenant_schema_registered",
        resource_type="tenant_schema_registry",
        resource_id=row.id,
        metadata={"schema_name": row.schema_name, "state": row.state},
    )
    db.commit()
    db.refresh(row)
    return row


@router.patch("/tenant-schemas/{business_id}", response_model=TenantSchemaOut)
def stage_tenant_schema(
    business_id: int,
    payload: TenantSchemaUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_platform_admin),
):
    try:
        row = update_registry(
            db,
            business_id,
            state=payload.state,
            feature_enabled=payload.feature_enabled,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record_audit(
        db,
        business_id=business_id,
        user_id=actor.id,
        action="platform_tenant_schema_staged",
        resource_type="tenant_schema_registry",
        resource_id=row.id,
        metadata={"schema_name": row.schema_name, "state": row.state, "feature_enabled": row.feature_enabled},
    )
    db.commit()
    db.refresh(row)
    return row
