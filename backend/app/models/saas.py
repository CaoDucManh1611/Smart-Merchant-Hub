"""Additive SaaS control-plane records kept beside the demo CRM database."""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


SCHEMA_NAME_RE = re.compile(r"^tenant_[1-9][0-9]*$")


def validate_tenant_schema_name(value: str) -> str:
    """Accept only deterministic tenant schema names for the future pilot."""
    name = str(value or "").strip().lower()
    if not SCHEMA_NAME_RE.fullmatch(name):
        raise ValueError("schema_name must match tenant_<business_id>")
    return name


class SaaSUsage(Base):
    __tablename__ = "saas_usage"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "resource",
            "period_start",
            name="uq_saas_usage_business_resource_period",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    resource: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    used: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    business = relationship("Business")
    reservations = relationship("QuotaReservation", back_populates="usage", cascade="all, delete-orphan")


class QuotaReservation(Base):
    __tablename__ = "saas_quota_reservations"
    __table_args__ = (
        UniqueConstraint("business_id", "idempotency_key", name="uq_saas_quota_reservation_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usage_id: Mapped[int] = mapped_column(ForeignKey("saas_usage.id", ondelete="CASCADE"), nullable=False, index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    resource: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    usage = relationship("SaaSUsage", back_populates="reservations")


class PlatformMembership(Base):
    __tablename__ = "platform_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user = relationship("User")


class DataLifecycleRequest(Base):
    __tablename__ = "data_lifecycle_requests"
    __table_args__ = (
        UniqueConstraint("business_id", "request_key", name="uq_data_lifecycle_business_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    request_key: Mapped[str] = mapped_column(String(180), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued", index=True)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    result_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    business = relationship("Business")
    requester = relationship("User", foreign_keys=[requested_by])


class TenantSchemaRegistry(Base):
    __tablename__ = "tenant_schema_registry"
    __table_args__ = (
        UniqueConstraint("business_id", name="uq_tenant_schema_business"),
        UniqueConstraint("schema_name", name="uq_tenant_schema_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    schema_name: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="proposed")
    feature_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    business = relationship("Business")
