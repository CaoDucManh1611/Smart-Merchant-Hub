"""Control-plane models stored only in the platform database."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.bases import PlatformBase


class PlatformBusiness(PlatformBase):
    __tablename__ = "platform_businesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PlatformUser(PlatformBase):
    __tablename__ = "platform_users"
    __table_args__ = (
        UniqueConstraint("business_id", "email", name="uq_platform_users_business_email"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int | None] = mapped_column(
        ForeignKey("platform_businesses.id", ondelete="CASCADE"), nullable=True, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="shop_agent")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PlatformAuthSession(PlatformBase):
    __tablename__ = "platform_auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PlatformRole(PlatformBase):
    __tablename__ = "platform_roles"
    __table_args__ = (UniqueConstraint("business_id", "code", name="uq_platform_roles_business_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int | None] = mapped_column(ForeignKey("platform_businesses.id", ondelete="CASCADE"), nullable=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class PlatformPermission(PlatformBase):
    __tablename__ = "platform_permissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class PlatformRolePermission(PlatformBase):
    __tablename__ = "platform_role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uq_platform_role_permission"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("platform_roles.id", ondelete="CASCADE"), nullable=False)
    permission_id: Mapped[int] = mapped_column(ForeignKey("platform_permissions.id", ondelete="CASCADE"), nullable=False)


class PlatformServicePlan(PlatformBase):
    __tablename__ = "platform_service_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    billing_cycle: Mapped[str] = mapped_column(String(20), nullable=False, default="monthly")
    quotas: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    features: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class PlatformSubscription(PlatformBase):
    __tablename__ = "platform_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("platform_businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("platform_service_plans.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PlatformPayment(PlatformBase):
    __tablename__ = "platform_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("platform_businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("platform_subscriptions.id", ondelete="CASCADE"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="VND")
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_transaction_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PlatformUsage(PlatformBase):
    __tablename__ = "platform_usage"
    __table_args__ = (
        UniqueConstraint("business_id", "resource", "period_start", name="uq_platform_usage_period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("platform_businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    resource: Mapped[str] = mapped_column(String(60), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)


class PlatformQuotaReservation(PlatformBase):
    __tablename__ = "platform_quota_reservations"
    __table_args__ = (
        UniqueConstraint("business_id", "idempotency_key", name="uq_platform_quota_reservation_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("platform_businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    resource: Mapped[str] = mapped_column(String(60), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PlatformMembership(PlatformBase):
    __tablename__ = "platform_memberships"
    __table_args__ = (UniqueConstraint("user_id", "business_id", name="uq_platform_membership_user_business"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False)
    business_id: Mapped[int] = mapped_column(ForeignKey("platform_businesses.id", ondelete="CASCADE"), nullable=False)
    role_code: Mapped[str] = mapped_column(String(80), nullable=False, default="shop_agent")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class TenantRegistry(PlatformBase):
    __tablename__ = "tenant_registry"
    __table_args__ = (
        UniqueConstraint("business_id", name="uq_tenant_registry_business"),
        UniqueConstraint("schema_name", name="uq_tenant_registry_schema"),
        CheckConstraint(
            "state IN ('provisioning','active','provision_failed','disabled','ready','migrating','error')",
            name="ck_tenant_registry_state",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("platform_businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    schema_name: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="provisioning")
    tenant_revision: Mapped[str | None] = mapped_column(String(80), nullable=True)
    migration_error: Mapped[str | None] = mapped_column(String(80), nullable=True)
    feature_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SupportGrant(PlatformBase):
    __tablename__ = "support_grants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("platform_businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    granted_by_user_id: Mapped[int] = mapped_column(ForeignKey("platform_users.id", ondelete="RESTRICT"), nullable=False)
    support_user_id: Mapped[int] = mapped_column(ForeignKey("platform_users.id", ondelete="RESTRICT"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list | dict] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ProvisioningOperation(PlatformBase):
    __tablename__ = "provisioning_operations"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_provisioning_operation_key"),
        CheckConstraint("state IN ('queued','running','succeeded','failed')", name="ck_provisioning_operation_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    business_id: Mapped[int] = mapped_column(ForeignKey("platform_businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class TenantMigrationOperation(PlatformBase):
    """Content-free ledger for one approved shop migration/cutover."""

    __tablename__ = "tenant_migration_operations"
    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_tenant_migration_operation_id"),
        CheckConstraint(
            "state IN ('migrating','copied','verified','active','rolled_back','failed')",
            name="ck_tenant_migration_operation_state",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("platform_businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="migrating")
    cursors: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    row_counts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    checksums: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    approved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PlatformAudit(PlatformBase):
    __tablename__ = "platform_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True)
    business_id: Mapped[int | None] = mapped_column(ForeignKey("platform_businesses.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PlatformProviderIncident(PlatformBase):
    """Redacted provider-health event; payloads remain in tenant storage."""

    __tablename__ = "platform_provider_incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("platform_businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    channel_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channel_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
