"""Tenant subscription quota checks and idempotent usage reservations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.business import ServicePlan, Subscription, User
from app.models.channel import Channel
from app.models.document import Document, DocumentChunk
from app.models.saas import QuotaReservation, SaaSUsage


QuotaResource = Literal[
    "staff_users",
    "connected_channels",
    "documents",
    "rag_chunks",
    "ai_calls",
    "ai_cost",
]

PLAN_LIMIT_FIELDS: dict[str, str] = {
    "staff_users": "max_users",
    "connected_channels": "max_channels",
    "documents": "max_documents",
    "rag_chunks": "max_rag_chunks",
    "ai_calls": "max_ai_calls",
    "ai_cost": "max_ai_cost",
}


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    resource: str
    used: Decimal
    limit: Decimal | None
    requested: Decimal
    period_start: datetime


class QuotaExceededError(RuntimeError):
    """Raised when a tenant would exceed its active plan quota."""

    def __init__(self, decision: QuotaDecision):
        self.resource = decision.resource
        self.used = decision.used
        self.limit = decision.limit
        self.requested = decision.requested
        self.period_start = decision.period_start
        super().__init__(f"Quota exceeded for {decision.resource}")

    @property
    def detail(self) -> dict:
        return {
            "code": "quota_exceeded",
            "resource": self.resource,
            "used": _json_number(self.used),
            "limit": _json_number(self.limit) if self.limit is not None else None,
            "requested": _json_number(self.requested),
            "period_start": self.period_start.isoformat(),
        }


def _json_number(value: Decimal | None):
    if value is None:
        return None
    return int(value) if value == value.to_integral_value() else float(value)


def _period_start(now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is not None:
        current = current.astimezone(timezone.utc).replace(tzinfo=None)
    return current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def quota_period_start(now: datetime | None = None) -> datetime:
    """Return the UTC period used by quota and platform usage reports."""
    return _period_start(now)


def _amount(value: int | float | Decimal | str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Quota amount must be numeric") from exc
    if result <= 0:
        raise ValueError("Quota amount must be greater than zero")
    return result


def _active_plan(db: Session, business_id: int) -> ServicePlan | None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = db.scalar(
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
    return row


def _limit_for(db: Session, business_id: int, resource: str) -> Decimal | None:
    field = PLAN_LIMIT_FIELDS.get(resource)
    if field is None:
        raise ValueError(f"Unknown quota resource: {resource}")
    plan = _active_plan(db, business_id)
    if plan is None:
        # Existing development fixtures predate subscriptions. Keep those
        # fixtures and local demos functional while production fails closed.
        if settings.ENVIRONMENT.strip().lower() != "production":
            return None
        return Decimal("0")
    return Decimal(str(getattr(plan, field) or 0))


def _current_usage(db: Session, business_id: int, resource: str, period_start: datetime) -> SaaSUsage | None:
    return db.scalar(
        select(SaaSUsage).where(
            SaaSUsage.business_id == business_id,
            SaaSUsage.resource == resource,
            SaaSUsage.period_start == period_start,
        )
    )


def _baseline_usage(db: Session, business_id: int, resource: str) -> Decimal:
    """Reflect pre-quota records when a tenant is upgraded in place."""
    if resource == "staff_users":
        value = db.scalar(
            select(func.count(User.id)).where(
                User.business_id == business_id,
                User.is_active.is_(True),
            )
        )
    elif resource == "connected_channels":
        value = db.scalar(
            select(func.count(Channel.id)).where(
                Channel.business_id == business_id,
                Channel.status == "active",
            )
        )
    elif resource == "documents":
        value = db.scalar(
            select(func.count(Document.id)).where(
                Document.business_id == business_id,
                Document.status != "deleted",
            )
        )
    elif resource == "rag_chunks":
        value = db.scalar(
            select(func.count(DocumentChunk.id))
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.business_id == business_id)
        )
    else:
        value = 0
    return Decimal(str(value or 0))


def _used_value(db: Session, business_id: int, resource: str, period_start: datetime) -> tuple[SaaSUsage | None, Decimal]:
    usage = _current_usage(db, business_id, resource, period_start)
    if usage is not None:
        return usage, Decimal(str(usage.used or 0))
    return None, _baseline_usage(db, business_id, resource)


def prime_quota(
    db: Session,
    business_id: int,
    resource: QuotaResource | str,
    *,
    now: datetime | None = None,
) -> SaaSUsage | None:
    """Materialize a baseline before a long-running mutation begins."""
    period_start = _period_start(now)
    if _limit_for(db, business_id, str(resource)) is None:
        return None
    usage = _current_usage(db, business_id, str(resource), period_start)
    if usage is not None:
        return usage
    usage = SaaSUsage(
        business_id=business_id,
        resource=str(resource),
        period_start=period_start,
        used=_baseline_usage(db, business_id, str(resource)),
    )
    db.add(usage)
    db.flush()
    return usage


def check_quota(
    db: Session,
    business_id: int,
    resource: QuotaResource | str,
    requested: int | float | Decimal | str = 1,
    *,
    now: datetime | None = None,
) -> QuotaDecision:
    amount = _amount(requested)
    period_start = _period_start(now)
    _usage_row, used = _used_value(db, business_id, str(resource), period_start)
    limit = _limit_for(db, business_id, str(resource))
    return QuotaDecision(
        allowed=limit is None or used + amount <= limit,
        resource=str(resource),
        used=used,
        limit=limit,
        requested=amount,
        period_start=period_start,
    )


def reserve_quota(
    db: Session,
    business_id: int,
    resource: QuotaResource | str,
    requested: int | float | Decimal | str = 1,
    *,
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> QuotaDecision:
    amount = _amount(requested)
    resource_name = str(resource)
    period_start = _period_start(now)

    if idempotency_key:
        existing = db.scalar(
            select(QuotaReservation).where(
                QuotaReservation.business_id == business_id,
                QuotaReservation.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            usage = db.get(SaaSUsage, existing.usage_id)
            return QuotaDecision(
                allowed=True,
                resource=existing.resource,
                used=Decimal(str(usage.used or 0)) if usage is not None else Decimal("0"),
                limit=_limit_for(db, business_id, existing.resource),
                requested=Decimal(str(existing.amount)),
                period_start=usage.period_start if usage is not None else period_start,
            )

    decision = check_quota(db, business_id, resource_name, amount, now=now)
    if not decision.allowed:
        raise QuotaExceededError(decision)
    if decision.limit is None:
        return decision

    usage, baseline = _used_value(db, business_id, resource_name, period_start)
    if usage is None:
        usage = SaaSUsage(
            business_id=business_id,
            resource=resource_name,
            period_start=period_start,
            used=baseline,
        )
        db.add(usage)
        db.flush()
    usage.used = Decimal(str(usage.used or 0)) + amount
    if idempotency_key:
        db.add(
            QuotaReservation(
                usage_id=usage.id,
                business_id=business_id,
                resource=resource_name,
                idempotency_key=idempotency_key,
                amount=amount,
            )
        )
    return QuotaDecision(
        allowed=True,
        resource=resource_name,
        used=usage.used,
        limit=decision.limit,
        requested=amount,
        period_start=period_start,
    )


def record_quota_usage(
    db: Session,
    business_id: int,
    resource: QuotaResource | str,
    amount: int | float | Decimal | str = 1,
    *,
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> QuotaDecision:
    """Record billable usage using the same guarded reservation path."""
    return reserve_quota(
        db,
        business_id,
        resource,
        amount,
        idempotency_key=idempotency_key,
        now=now,
    )


def release_quota(
    db: Session,
    business_id: int,
    resource: QuotaResource | str,
    amount: int | float | Decimal | str = 1,
    *,
    now: datetime | None = None,
) -> QuotaDecision:
    """Release capacity for resources that represent current inventory.

    AI calls remain cumulative and are never released. This helper is used
    when a document or channel is removed so a tenant can use the freed slot
    again during the same billing period.
    """
    resource_name = str(resource)
    if resource_name in {"ai_calls", "ai_cost"}:
        raise ValueError(f"Cannot release cumulative quota resource: {resource_name}")
    release_amount = _amount(amount)
    period_start = _period_start(now)
    usage = _current_usage(db, business_id, resource_name, period_start)
    limit = _limit_for(db, business_id, resource_name)
    if usage is None:
        used = _baseline_usage(db, business_id, resource_name)
    else:
        used = max(Decimal("0"), Decimal(str(usage.used or 0)) - release_amount)
        usage.used = used
    return QuotaDecision(
        allowed=True,
        resource=resource_name,
        used=used,
        limit=limit,
        requested=-release_amount,
        period_start=period_start,
    )
