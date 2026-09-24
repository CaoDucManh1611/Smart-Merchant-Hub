"""Tenant-independent platform administration APIs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Response
from sqlalchemy import String, cast, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.platform import require_platform_admin
from app.database.bootstrap import ensure_default_plans
from app.db.dependencies import get_db
from app.database.platform_session import get_platform_db
from app.models.audit_log import AuditLog
from app.models.auth_session import AuthSession
from app.models.business import Business, Payment, ServicePlan, Subscription, User
from app.models.channel import Channel, ChannelEvent
from app.models.saas import SaaSUsage
from app.models.platform_control import PlatformAudit, PlatformProviderIncident
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
    PlatformSubscriptionApprovalOut,
    PlatformSubscriptionOut,
    PlatformSubscriptionRequestListOut,
    PlatformSubscriptionRequestOut,
    PlatformSubscriptionUpdate,
    PlatformPaymentCreate,
    PlatformPaymentOut,
    PlatformProviderErrorOut,
    PlatformPrivacyRequest,
    PlatformPrivacyOut,
    ProvisioningOut,
    ProvisioningRequest,
)
from app.services.audit_service import record_audit
from app.services.quota_service import PLAN_LIMIT_FIELDS, quota_period_start
from app.services.privacy_service import get_or_create_request
from app.services.tenant_schema_service import ensure_registry, update_registry
from app.models.platform_control import PlatformBusiness, TenantRegistry
from app.tenancy.provisioning import provision_shop, retry_provision_shop, ProvisioningValidationError


router = APIRouter(prefix="/platform")
logger = logging.getLogger(__name__)


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


def _record_plan_audit(
    db: Session,
    platform_db: Session,
    actor: User,
    *,
    action: str,
    plan: ServicePlan,
) -> None:
    """Write plan changes to the correct audit store.

    Platform admins are intentionally not attached to a shop, so the legacy
    tenant audit table cannot accept their ``NULL`` business id. Keep shop
    admins on the existing audit path and use the control-plane audit table
    for global plan changes.
    """

    metadata = {"code": plan.code, "status": plan.status, "legacy_actor_user_id": actor.id}
    if actor.business_id is not None:
        record_audit(
            db,
            business_id=actor.business_id,
            user_id=actor.id,
            action=action,
            resource_type="service_plan",
            resource_id=plan.id,
            metadata=metadata,
        )
        return
    platform_db.add(
        PlatformAudit(
            actor_user_id=None,
            business_id=None,
            action=action,
            resource_type="service_plan",
            resource_id=str(plan.id),
            metadata_json=metadata,
        )
    )


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


def _platform_quota_snapshot(db: Session, business_id: int, period_start, plan: ServicePlan | None) -> dict:
    """Build metadata-only quota counters from platform usage aggregates.

    This function deliberately never counts users, channels, documents or any
    other tenant table.  Tenant services must write aggregate usage events to
    ``saas_usage``; a missing row is reported as zero rather than sampled.
    """

    usage = _usage_for(db, business_id, period_start)
    resources = {}
    warning = 0.8
    for resource, field in PLAN_LIMIT_FIELDS.items():
        used = float(usage.get(resource, 0) or 0)
        limit_value = getattr(plan, field, None) if plan is not None else None
        limit = _number(limit_value) if limit_value is not None else None
        percent = (used / float(limit) * 100) if limit not in (None, 0) else (100.0 if used > 0 else 0.0 if limit == 0 else None)
        resources[resource] = {
            "used": int(used) if used.is_integer() else used,
            "limit": limit,
            "percent": percent,
            "near_limit": bool(limit is not None and used >= float(limit) * warning),
            "exceeded": bool(limit is not None and used > float(limit)),
        }
    return {
        "business_id": int(business_id),
        "period_start": period_start,
        "plan_code": plan.code if plan else None,
        "plan_name": plan.name if plan else None,
        "warning_percent": warning,
        "resources": resources,
    }


def _shop_out(db: Session, business: Business, period_start) -> PlatformShopOut:
    plan = _plan_for(db, business.id)
    quota = _platform_quota_snapshot(db, business.id, period_start, plan)
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
        service_type=row.service_type or "package",
        status=row.status,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        auto_renew=row.auto_renew,
        created_at=row.created_at,
    )


def _subscription_request_out(db: Session, row: Subscription) -> PlatformSubscriptionRequestOut:
    """Return only the shop contact and requested package to platform admins."""

    business = db.get(Business, row.business_id)
    if business is None:  # Defensive: the FK normally prevents this.
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    owner = db.scalar(
        select(User)
        .where(User.business_id == business.id, User.role == "owner")
        .order_by(User.id.asc())
    )
    if owner is None:
        owner = db.scalar(
            select(User)
            .where(User.business_id == business.id, User.role == "admin")
            .order_by(User.id.asc())
        )
    latest_request = db.scalar(
        select(AuditLog)
        .where(
            AuditLog.business_id == business.id,
            AuditLog.action == "subscription_request_submitted",
            AuditLog.resource_type == "subscription",
            AuditLog.resource_id == str(row.id),
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(1)
    )
    requester = (
        db.get(User, latest_request.user_id)
        if latest_request is not None and latest_request.user_id is not None
        else None
    )
    metadata = latest_request.metadata_ if latest_request is not None else {}
    request_details = metadata.get("request_details", {}) if isinstance(metadata, dict) else {}
    if not isinstance(request_details, dict):
        request_details = {}
    requested_channels = request_details.get("channels", [])
    if not isinstance(requested_channels, list):
        requested_channels = []
    requested_at = latest_request.created_at if latest_request is not None else row.created_at
    if requested_at is not None and requested_at.tzinfo is None:
        # All legacy subscription/audit timestamps are stored as naive UTC.
        requested_at = requested_at.replace(tzinfo=timezone.utc)
    return PlatformSubscriptionRequestOut(
        subscription_id=row.id,
        business_id=business.id,
        shop_name=business.name,
        shop_slug=business.slug,
        requester_name=requester.full_name if requester is not None else (owner.full_name if owner is not None else None),
        requester_email=requester.email if requester is not None else (owner.email if owner is not None else business.email),
        requested_at=requested_at,
        contact_name=request_details.get("contact_name"),
        contact_email=request_details.get("contact_email"),
        contact_phone=request_details.get("contact_phone"),
        requested_shop_name=request_details.get("shop_name"),
        requested_channels=[channel for channel in requested_channels if isinstance(channel, str)],
        request_notes=request_details.get("notes"),
        owner_name=owner.full_name if owner is not None else None,
        owner_email=owner.email if owner is not None else business.email,
        plan_id=row.plan_id,
        plan_code=row.plan.code,
        plan_name=row.plan.name,
        service_type=row.service_type or "package",
        status="pending",
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
    # Older development databases may have the service_plans table but no
    # catalogue rows yet.  Repair that state idempotently so Admin is usable
    # immediately after migration instead of showing an empty catalogue.
    ensure_default_plans(db)
    db.commit()
    return db.scalars(select(ServicePlan).order_by(ServicePlan.status.asc(), ServicePlan.id.asc())).all()


@router.post("/plans", response_model=PlatformPlanOut, status_code=201)
def create_plan(
    payload: PlatformPlanCreate,
    db: Session = Depends(get_db),
    platform_db: Session = Depends(get_platform_db),
    actor: User = Depends(require_platform_admin),
):
    plan = ServicePlan(**payload.model_dump())
    db.add(plan)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Mã gói dịch vụ đã tồn tại.") from exc
    _record_plan_audit(db, platform_db, actor, action="platform_plan_created", plan=plan)
    db.commit()
    if platform_db is not db:
        platform_db.commit()
    db.refresh(plan)
    return plan


@router.patch("/plans/{plan_id}", response_model=PlatformPlanOut)
def update_plan(
    plan_id: int,
    payload: PlatformPlanCreate,
    db: Session = Depends(get_db),
    platform_db: Session = Depends(get_platform_db),
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
    _record_plan_audit(db, platform_db, actor, action="platform_plan_updated", plan=plan)
    db.commit()
    if platform_db is not db:
        platform_db.commit()
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


@router.get("/subscription-requests", response_model=PlatformSubscriptionRequestListOut)
def list_subscription_requests(
    db: Session = Depends(get_db),
    _actor: User = Depends(require_platform_admin),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List only outstanding package requests; never expose tenant CRM data."""

    base_query = select(Subscription).where(Subscription.status == "pending")
    total = int(db.scalar(select(func.count(Subscription.id)).where(Subscription.status == "pending")) or 0)
    latest_request_at = (
        select(func.max(AuditLog.created_at))
        .where(
            AuditLog.business_id == Subscription.business_id,
            AuditLog.action == "subscription_request_submitted",
            AuditLog.resource_type == "subscription",
            AuditLog.resource_id == cast(Subscription.id, String),
        )
        .correlate(Subscription)
        .scalar_subquery()
    )
    rows = db.scalars(
        base_query
        .order_by(func.coalesce(latest_request_at, Subscription.created_at).desc(), Subscription.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return PlatformSubscriptionRequestListOut(
        items=[_subscription_request_out(db, row) for row in rows],
        total=total,
    )


@router.post(
    "/subscription-requests/{subscription_id}/approve",
    response_model=PlatformSubscriptionApprovalOut,
)
def approve_subscription_request(
    subscription_id: int,
    db: Session = Depends(get_db),
    platform_db: Session = Depends(get_platform_db),
    actor: User = Depends(require_platform_admin),
):
    """Activate one approved request, then start the idempotent tenant saga."""

    row = db.scalar(select(Subscription).where(Subscription.id == subscription_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Yêu cầu gói dịch vụ không tồn tại.")
    if row.status != "pending":
        raise HTTPException(status_code=409, detail="Yêu cầu này không còn ở trạng thái chờ duyệt.")
    plan = db.get(ServicePlan, row.plan_id)
    if plan is None or plan.status != "active":
        raise HTTPException(status_code=409, detail="Gói dịch vụ đã ngừng bán và không thể duyệt.")
    business = db.get(Business, row.business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")

    # Keep at most one active package. Existing active access remains usable
    # until this point, so requesting an upgrade never locks a shop early.
    for active_row in db.scalars(
        select(Subscription).where(
            Subscription.business_id == business.id,
            Subscription.service_type == (row.service_type or "package"),
            Subscription.status == "active",
            Subscription.id != row.id,
        )
    ):
        active_row.status = "cancelled"
    row.status = "active"
    row.starts_at = datetime.now(timezone.utc).replace(tzinfo=None)
    row.ends_at = None
    db.flush()
    record_audit(
        db,
        business_id=business.id,
        user_id=actor.id,
        action="platform_subscription_approved",
        resource_type="subscription",
        resource_id=row.id,
        metadata={"plan_code": plan.code, "service_type": row.service_type or "package"},
    )
    db.commit()
    db.refresh(row)

    try:
        if row.service_type == "package":
            # Paid CRM approvals must update the control-plane quota now. A
            # chatbot approval intentionally skips this mirror because it is
            # an add-on and must not replace the shop's CRM package.
            from app.api.onboarding import _sync_platform_subscription

            _sync_platform_subscription(platform_db, business, plan)
        _sync_platform_business(platform_db, db, business.id)
        registry = provision_shop(
            platform_db,
            business_id=business.id,
            idempotency_key=f"platform-subscription-approval-{row.id}",
        )
    except ProvisioningValidationError:
        platform_db.rollback()
        raise HTTPException(
            status_code=422,
            detail="Gói đã được duyệt nhưng không gian dữ liệu chưa thể chuẩn bị. Hãy kiểm tra cấu hình tenant và thử lại.",
        ) from None
    except Exception:  # noqa: BLE001 - never return infrastructure details to the admin UI
        platform_db.rollback()
        logger.warning("Tenant provisioning deferred after subscription approval id=%s", row.id, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Gói đã được duyệt nhưng hệ thống chưa thể chuẩn bị không gian dữ liệu. Hãy thử lại sau.",
        ) from None

    return PlatformSubscriptionApprovalOut(
        subscription=_subscription_out(row),
        provisioning=ProvisioningOut(
            business_id=registry.business_id,
            schema_name=registry.schema_name,
            state=registry.state,
            feature_enabled=registry.feature_enabled,
            subscription_active=True,
            subscription_status="active",
            tenant_revision=registry.tenant_revision,
            migration_error=registry.migration_error,
        ),
    )


@router.post("/subscription-requests/{subscription_id}/reject", response_model=PlatformSubscriptionOut)
def reject_subscription_request(
    subscription_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(require_platform_admin),
):
    """Close an unapproved request without altering an existing active plan."""

    row = db.scalar(select(Subscription).where(Subscription.id == subscription_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Yêu cầu gói dịch vụ không tồn tại.")
    if row.status != "pending":
        raise HTTPException(status_code=409, detail="Yêu cầu này không còn ở trạng thái chờ duyệt.")
    row.status = "cancelled"
    db.flush()
    record_audit(
        db,
        business_id=row.business_id,
        user_id=actor.id,
        action="platform_subscription_rejected",
        resource_type="subscription",
        resource_id=row.id,
        metadata={"plan_code": row.plan.code, "service_type": row.service_type or "package"},
    )
    db.commit()
    db.refresh(row)
    return _subscription_out(row)


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
        .where(
            Subscription.business_id == business_id,
            Subscription.service_type == "package",
        )
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
        .where(
            Subscription.business_id == business_id,
            Subscription.service_type == "package",
        )
        .order_by(Subscription.id.desc())
    )
    if row is None:
        row = Subscription(business_id=business_id, service_type="package")
        db.add(row)
    elif row.status == "active" and row.plan_id != plan.id:
        row.status = "cancelled"
        row = Subscription(business_id=business_id, service_type="package")
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
    if payload.status == "paid" and subscription.plan is not None and payload.amount != subscription.plan.price:
        raise HTTPException(status_code=409, detail="Số tiền thanh toán không khớp giá gói dịch vụ.")
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
    if payload.status == "suspended":
        # Suspending a shop immediately invalidates every bearer session. A
        # later reactivation requires a fresh login and cannot reuse a token
        # captured before the lifecycle transition.
        db.query(AuthSession).filter(
            AuthSession.user_id.in_(select(User.id).where(User.business_id == business_id)),
            AuthSession.revoked_at.is_(None),
        ).update({AuthSession.revoked_at: datetime.now(timezone.utc).replace(tzinfo=None)}, synchronize_session=False)
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
    quota = _platform_quota_snapshot(db, business_id, period_start, plan)
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
    legacy_db: Session = Depends(get_db),
    platform_db: Session = Depends(get_platform_db),
    _actor: User = Depends(require_platform_admin),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Return redacted provider delivery failures for platform operators."""
    # The production control plane stores only a redacted incident aggregate.
    # It can therefore be queried when tenant tables are unavailable.
    if platform_db.bind is not None:
        try:
            table_names = set(inspect(platform_db.bind).get_table_names())
        except Exception:  # pragma: no cover - defensive readiness path
            table_names = set()
        if "platform_provider_incidents" in table_names:
            query = select(PlatformProviderIncident).where(
                PlatformProviderIncident.status == "failed"
            ).order_by(PlatformProviderIncident.received_at.desc(), PlatformProviderIncident.id.desc()).limit(limit)
            if business_id is not None:
                query = query.where(PlatformProviderIncident.business_id == business_id)
            rows = platform_db.scalars(query).all()
            return [
                PlatformProviderErrorOut(
                    id=row.id,
                    business_id=row.business_id,
                    channel_id=row.channel_id,
                    channel_type=row.channel_type,
                    event_type=row.event_type,
                    status=row.status,
                    error_type=row.error_type,
                    received_at=row.received_at,
                )
                for row in rows
            ]

    # Legacy compatibility is retained only for isolated development
    # databases that have no platform incident table yet.
    query = (
        select(ChannelEvent, Channel.channel_type)
        .join(Channel, Channel.id == ChannelEvent.channel_id)
        .where(ChannelEvent.status == "failed")
        .order_by(ChannelEvent.received_at.desc(), ChannelEvent.id.desc())
        .limit(limit)
    )
    if business_id is not None:
        query = query.where(Channel.business_id == business_id)
    rows = legacy_db.execute(query).all()
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
        # Platform only records and dispatches the request.  Export execution
        # happens in the tenant worker after it resolves the shop schema.
        row.result_metadata = {"counts": {}, "dispatch": "tenant_worker"}
        record_audit(db, business_id=business_id, user_id=actor.id, action="platform_privacy_export_queued", resource_type="data_lifecycle_request", resource_id=row.id, metadata={"dispatch": "tenant_worker"})
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
        row.result_metadata = {"counts": {}, "dispatch": "tenant_worker"}
        record_audit(db, business_id=business_id, user_id=actor.id, action="platform_privacy_anonymize_queued", resource_type="data_lifecycle_request", resource_id=row.id, metadata={"dispatch": "tenant_worker"})
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
        row.result_metadata = {"counts": {}, "dispatch": "tenant_worker", "mode": "anonymize_retained_orders"}
        record_audit(db, business_id=business_id, user_id=actor.id, action="platform_privacy_delete_queued", resource_type="data_lifecycle_request", resource_id=row.id, metadata={"dispatch": "tenant_worker", "mode": "anonymize_retained_orders"})
        db.commit()
    return PlatformPrivacyOut(id=row.id, business_id=business_id, kind=row.kind, status=row.status, counts=(row.result_metadata or {}).get("counts", {}))


@router.get("/audit-logs", response_model=list[PlatformAuditOut])
def list_platform_audit_logs(
    db: Session = Depends(get_db),
    _actor: User = Depends(require_platform_admin),
    limit: int = Query(default=100, ge=1, le=500),
):
    # Once the control-plane database has its own audit table, never fall back
    # to tenant ``audit_logs``.  The fallback is kept only for old isolated
    # development databases that predate the platform schema migration.
    if db.bind is not None:
        try:
            table_names = set(inspect(db.bind).get_table_names())
        except Exception:  # pragma: no cover - defensive readiness path
            table_names = set()
        if "platform_audit" in table_names:
            rows = db.scalars(
                select(PlatformAudit)
                .where(PlatformAudit.action.like("platform_%"))
                .order_by(PlatformAudit.created_at.desc(), PlatformAudit.id.desc())
                .limit(limit)
            ).all()
            return [
                PlatformAuditOut(
                    id=row.id,
                    event_id=f"platform-{row.id}",
                    business_id=int(row.business_id or 0),
                    user_id=row.actor_user_id,
                    actor_type="platform",
                    action=row.action,
                    resource_type=row.resource_type or "platform",
                    resource_id=row.resource_id,
                    metadata=row.metadata_json or {},
                    created_at=row.created_at,
                )
                for row in rows
            ]
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
    if db.bind is not None:
        try:
            table_names = set(inspect(db.bind).get_table_names())
        except Exception:  # pragma: no cover - defensive readiness path
            table_names = set()
        if "platform_audit" in table_names:
            rows = db.scalars(
                select(PlatformAudit)
                .order_by(PlatformAudit.created_at.desc(), PlatformAudit.id.desc())
                .limit(limit)
            ).all()
            return [
                PlatformAuditOut(
                    id=row.id,
                    event_id=f"platform-{row.id}",
                    business_id=int(row.business_id or 0),
                    user_id=row.actor_user_id,
                    actor_type="platform",
                    action=row.action,
                    resource_type=row.resource_type or "platform",
                    resource_id=row.resource_id,
                    metadata=row.metadata_json or {},
                    created_at=row.created_at,
                )
                for row in rows
            ]
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


def _sync_platform_business(platform_db: Session, legacy_db: Session, business_id: int) -> PlatformBusiness:
    """Mirror only shop identity into the platform DB for rollout compatibility."""

    platform_business = platform_db.get(PlatformBusiness, business_id)
    if platform_business is not None:
        return platform_business
    legacy_business = legacy_db.get(Business, business_id)
    if legacy_business is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại.")
    platform_business = PlatformBusiness(id=business_id, name=legacy_business.name, slug=legacy_business.slug, status=legacy_business.status)
    platform_db.add(platform_business)
    platform_db.flush()
    return platform_business


@router.post("/shops/{business_id}/provision", response_model=ProvisioningOut)
def provision_shop_schema(
    business_id: int,
    payload: ProvisioningRequest | None = Body(default=None),
    idempotency_key: str | None = Query(default=None, min_length=8, max_length=180),
    idempotency_header: str | None = Header(default=None, alias="Idempotency-Key"),
    legacy_db: Session = Depends(get_db),
    platform_db: Session = Depends(get_platform_db),
    _actor: User = Depends(require_platform_admin),
):
    _sync_platform_business(platform_db, legacy_db, business_id)
    key = (payload.idempotency_key if payload else None) or idempotency_key or idempotency_header
    if not key:
        raise HTTPException(status_code=422, detail="Cần idempotency_key hoặc Idempotency-Key.")
    try:
        row = provision_shop(platform_db, business_id=business_id, idempotency_key=key)
    except ProvisioningValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    platform_db.refresh(row)
    return row


@router.post("/shops/{business_id}/provision/retry", response_model=ProvisioningOut)
def retry_shop_schema(
    business_id: int,
    payload: ProvisioningRequest | None = Body(default=None),
    idempotency_key: str | None = Query(default=None, min_length=8, max_length=180),
    idempotency_header: str | None = Header(default=None, alias="Idempotency-Key"),
    legacy_db: Session = Depends(get_db),
    platform_db: Session = Depends(get_platform_db),
    _actor: User = Depends(require_platform_admin),
):
    _sync_platform_business(platform_db, legacy_db, business_id)
    key = (payload.idempotency_key if payload else None) or idempotency_key or idempotency_header
    if not key:
        raise HTTPException(status_code=422, detail="Cần idempotency_key hoặc Idempotency-Key.")
    try:
        row = retry_provision_shop(platform_db, business_id=business_id, idempotency_key=key)
    except ProvisioningValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    platform_db.refresh(row)
    return row
