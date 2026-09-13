"""Tenant-independent platform administration APIs."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.platform import require_platform_admin
from app.db.dependencies import get_db
from app.models.audit_log import AuditLog
from app.models.business import Business, Payment, ServicePlan, Subscription, User
from app.models.channel import Channel, ChannelEvent
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
    PlatformProviderErrorOut,
    PlatformPrivacyRequest,
    PlatformPrivacyOut,
)
from app.services.audit_service import record_audit
from app.services.quota_service import PLAN_LIMIT_FIELDS, quota_period_start, quota_snapshot
from app.services.privacy_service import anonymize_customer_data, complete_request, export_customer_data, get_or_create_request
from app.services.tenant_schema_service import ensure_registry, update_registry


router = APIRouter(prefix="/platform")


def _provider_error_type(message: str | None) -> str | None:
    """Classify a provider failure without returning customer text or secrets."""
    if not message:
        return None
    folded = str(message).casefold()
    if any(term in folded for term in ("401", "403", "unauthorized", "forbidden", "invalid token", "signature")):
        return "authentication"
    if any(term in folded for term in ("429", "rate limit", "too many")):
        return "rate_limit"
    if any(term in folded for term in ("timeout", "timed out", "deadline")):
        return "timeout"
    if any(term in folded for term in ("500", "502", "503", "504", "server error")):
        return "provider_unavailable"
    if any(term in folded for term in ("400", "invalid", "validation", "bad request")):
        return "validation"
    return "unknown"


def _same_payment_identity(existing: Payment, payload: PlatformPaymentCreate) -> bool:
    return (
        existing.subscription_id == payload.subscription_id
        and existing.amount == payload.amount
        and existing.currency.upper() == payload.currency.strip().upper()
        and existing.provider == payload.provider.strip().lower()
    )


def _apply_payment_status(existing: Payment, payload: PlatformPaymentCreate) -> bool:
    """Apply a legitimate provider status transition; reject regressions."""
    if existing.status == payload.status:
        return False
    allowed = {
        "pending": {"paid", "failed"},
        "paid": {"refunded"},
        "failed": set(),
        "refunded": set(),
    }
    if payload.status not in allowed.get(existing.status, set()):
        raise HTTPException(status_code=409, detail="Trạng thái giao dịch không thể chuyển đổi theo thứ tự này.")
    existing.status = payload.status
    if existing.status == "paid":
        existing.paid_at = payload.paid_at or datetime.now(timezone.utc).replace(tzinfo=None)
    return True


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
    quota = quota_snapshot(db, business.id, now=period_start)
    return PlatformShopOut(
        id=business.id,
        name=business.name,
        slug=business.slug,
        status=business.status,
        plan_code=plan.code if plan else None,
        plan_name=plan.name if plan else None,
        usage=_usage_for(db, business.id, period_start),
        quota=quota,
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
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    period_start = quota_period_start()
    query = select(Business).order_by(Business.id.asc())
    shops = db.scalars(query.offset(offset).limit(limit)).all()
    total_count = db.scalar(select(func.count(Business.id))) or 0
    return PlatformShopListOut(
        items=[_shop_out(db, shop, period_start) for shop in shops],
        total=int(total_count),
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
    transaction_id = payload.provider_transaction_id.strip()
    existing = db.scalar(
        select(Payment).where(Payment.provider_transaction_id == transaction_id)
    )
    if existing is not None:
        if existing.business_id != business_id:
            raise HTTPException(status_code=409, detail="Mã giao dịch đã thuộc shop khác.")
        if not _same_payment_identity(existing, payload):
            raise HTTPException(status_code=409, detail="Mã giao dịch đã tồn tại với số tiền hoặc nguồn khác.")
        changed = _apply_payment_status(existing, payload)
        if changed:
            if existing.status == "paid" and subscription.status == "pending":
                subscription.status = "active"
            record_audit(
                db,
                business_id=business_id,
                user_id=actor.id,
                action="platform_payment_updated",
                resource_type="subscription_payment",
                resource_id=existing.id,
                metadata={"subscription_id": subscription.id, "status": existing.status, "provider": existing.provider},
            )
            db.commit()
            db.refresh(existing)
        response.status_code = 200
        return existing
    payment = Payment(
        business_id=business_id,
        subscription_id=subscription.id,
        amount=payload.amount,
        currency=payload.currency.upper(),
        provider=payload.provider.strip().lower(),
        provider_transaction_id=transaction_id,
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
        existing = db.scalar(select(Payment).where(Payment.provider_transaction_id == transaction_id))
        if existing is None or existing.business_id != business_id:
            raise HTTPException(status_code=409, detail="Mã giao dịch đã tồn tại.") from exc
        if not _same_payment_identity(existing, payload) or existing.status != payload.status:
            raise HTTPException(status_code=409, detail="Mã giao dịch đã tồn tại với dữ liệu khác.") from exc
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
    quota = quota_snapshot(db, business_id, now=period_start)
    return PlatformUsageOut(
        business_id=business_id,
        period_start=period_start,
        plan_code=plan.code if plan else None,
        limits=limits,
        usage=_usage_for(db, business_id, period_start),
        quota=quota,
        warnings=[
            {"resource": resource, **details}
            for resource, details in quota["resources"].items()
            if details.get("near_limit")
        ],
    )


@router.get("/provider-errors", response_model=list[PlatformProviderErrorOut])
def list_provider_errors(
    business_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    _actor: User = Depends(require_platform_admin),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Return redacted provider delivery failures for platform operators."""
    query = (
        select(ChannelEvent, Channel.channel_type)
        .join(Channel, Channel.id == ChannelEvent.channel_id)
        .where(ChannelEvent.status == "failed")
        .order_by(ChannelEvent.received_at.desc(), ChannelEvent.id.desc())
        .limit(limit)
    )
    if business_id is not None:
        query = query.where(Channel.business_id == business_id)
    rows = db.execute(query).all()
    return [
        PlatformProviderErrorOut(
            id=event.id,
            business_id=event.channel.business_id,
            channel_id=event.channel_id,
            channel_type=channel_type,
            event_type=event.event_type,
            status=event.status,
            error_type=_provider_error_type(event.error_message),
            received_at=event.received_at,
        )
        for event, channel_type in rows
    ]


def _platform_privacy_business(db: Session, business_id: int) -> Business:
    business = db.get(Business, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    return business


@router.post("/shops/{business_id}/privacy/export", response_model=PlatformPrivacyOut)
def platform_export_data(
    business_id: int,
    payload: PlatformPrivacyRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_platform_admin),
):
    _platform_privacy_business(db, business_id)
    try:
        row, created = get_or_create_request(
            db,
            business_id=business_id,
            request_key=payload.request_key,
            kind="export",
            requested_by=actor.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if created:
        _data, counts = export_customer_data(db, business_id)
        complete_request(row, counts=counts)
        record_audit(db, business_id=business_id, user_id=actor.id, action="platform_privacy_export", resource_type="data_lifecycle_request", resource_id=row.id, metadata={"counts": counts})
        db.commit()
    return PlatformPrivacyOut(id=row.id, business_id=business_id, kind=row.kind, status=row.status, counts=(row.result_metadata or {}).get("counts", {}))


@router.post("/shops/{business_id}/privacy/anonymize", response_model=PlatformPrivacyOut)
def platform_anonymize_data(
    business_id: int,
    payload: PlatformPrivacyRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_platform_admin),
):
    _platform_privacy_business(db, business_id)
    try:
        row, created = get_or_create_request(db, business_id=business_id, request_key=payload.request_key, kind="anonymize", requested_by=actor.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if created:
        counts = anonymize_customer_data(db, business_id)
        complete_request(row, counts=counts)
        record_audit(db, business_id=business_id, user_id=actor.id, action="platform_privacy_anonymize", resource_type="data_lifecycle_request", resource_id=row.id, metadata={"counts": counts})
        db.commit()
    return PlatformPrivacyOut(id=row.id, business_id=business_id, kind=row.kind, status=row.status, counts=(row.result_metadata or {}).get("counts", {}))


@router.post("/shops/{business_id}/privacy/delete", response_model=PlatformPrivacyOut)
def platform_delete_data(
    business_id: int,
    payload: PlatformPrivacyRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_platform_admin),
):
    if payload.confirmation_token != "DELETE":
        raise HTTPException(status_code=422, detail="Cần confirmation_token=DELETE để xác nhận.")
    _platform_privacy_business(db, business_id)
    try:
        row, created = get_or_create_request(db, business_id=business_id, request_key=payload.request_key, kind="delete", requested_by=actor.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if created:
        counts = anonymize_customer_data(db, business_id, deleted=True)
        complete_request(row, counts=counts)
        record_audit(db, business_id=business_id, user_id=actor.id, action="platform_privacy_delete", resource_type="data_lifecycle_request", resource_id=row.id, metadata={"counts": counts, "mode": "anonymized_retained_orders"})
        db.commit()
    return PlatformPrivacyOut(id=row.id, business_id=business_id, kind=row.kind, status=row.status, counts=(row.result_metadata or {}).get("counts", {}))


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
