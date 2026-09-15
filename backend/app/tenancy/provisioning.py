"""Retryable, non-destructive provisioning saga for one shop schema."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.tenant_session import tenant_engine, tenant_session
from app.models.platform_control import PlatformBusiness, ProvisioningOperation, TenantRegistry
from app.tenancy.migration_runner import current_tenant_revision, upgrade_tenant_schema
from app.tenancy.schema import schema_name_for, validate_schema_name


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _error_code(exc: Exception) -> str:
    """Return a bounded operational code; never persist exception text."""
    return type(exc).__name__.lower().replace(" ", "_")[:80] or "provisioning_failed"


def _platform_business(platform_db: Session, business_id: int) -> PlatformBusiness | None:
    try:
        return platform_db.scalar(
            select(PlatformBusiness).where(PlatformBusiness.id == int(business_id))
        )
    except Exception:
        # A legacy rollout database may not have the new control-plane tables
        # yet.  The caller gets a retryable failure rather than a silent
        # fallback to a shared tenant schema.
        return None


def provision_shop(
    platform_db: Session,
    *,
    business_id: int,
    idempotency_key: str,
    migrate: Callable | None = None,
    seed: Callable[[Session, int], None] | None = None,
    revision_lookup: Callable[[str], str | None] | None = None,
) -> TenantRegistry:
    """Provision exactly one validated schema and mark it active on success.

    The platform transaction records an operation before touching the tenant
    database.  A failed migration leaves the schema and registry in a retryable
    ``error`` state; no data-bearing schema is ever dropped automatically.
    ``migrate`` and ``seed`` are injectable for tests and controlled pilots.
    """
    shop_id = int(business_id)
    if shop_id <= 0:
        raise ValueError("business_id must be positive")
    key = str(idempotency_key or "").strip()
    if not key or len(key) > 180:
        raise ValueError("idempotency_key is required")
    schema = schema_name_for(shop_id)
    validate_schema_name(schema)

    business = _platform_business(platform_db, shop_id)
    if business is None:
        raise LookupError("Platform business not found")

    operation = platform_db.scalar(
        select(ProvisioningOperation).where(
            ProvisioningOperation.idempotency_key == key,
        ).with_for_update()
    )
    if operation is None:
        operation = ProvisioningOperation(
            idempotency_key=key,
            business_id=shop_id,
            state="queued",
            attempt_count=0,
        )
        platform_db.add(operation)
        platform_db.flush()
    elif int(operation.business_id) != shop_id:
        raise PermissionError("Idempotency key belongs to another shop")

    registry = platform_db.scalar(
        select(TenantRegistry).where(TenantRegistry.business_id == shop_id).with_for_update()
    )
    if registry is None:
        registry = TenantRegistry(
            business_id=shop_id,
            schema_name=schema,
            state="provisioning",
            feature_enabled=False,
        )
        platform_db.add(registry)
        platform_db.flush()
    elif validate_schema_name(str(registry.schema_name)) != schema:
        raise RuntimeError("Tenant registry schema does not match business")

    if operation.state == "succeeded" and registry.state == "active":
        return registry
    if registry.state == "active" and registry.feature_enabled:
        operation.state = "succeeded"
        platform_db.flush()
        return registry

    operation.state = "running"
    operation.attempt_count = int(operation.attempt_count or 0) + 1
    operation.last_error_code = None
    registry.state = "provisioning"
    registry.feature_enabled = False
    registry.migration_error = None
    registry.updated_at = _now()
    platform_db.flush()
    platform_db.commit()

    try:
        if migrate is not None:
            revision = str(migrate(schema)).strip()
        else:
            with tenant_engine.begin() as connection:
                revision = upgrade_tenant_schema(connection, schema)
        if not revision:
            raise RuntimeError("tenant_revision_missing")

        if seed is not None:
            with tenant_session(schema) as tenant_db:
                seed(tenant_db, shop_id)

        if revision_lookup is not None:
            current = revision_lookup(schema)
        else:
            with tenant_engine.connect() as connection:
                current = current_tenant_revision(connection, schema)
        if not current or current != revision:
            raise RuntimeError("tenant_revision_mismatch")

        registry = platform_db.scalar(
            select(TenantRegistry).where(TenantRegistry.business_id == shop_id).with_for_update()
        )
        operation = platform_db.scalar(
            select(ProvisioningOperation).where(ProvisioningOperation.idempotency_key == key).with_for_update()
        )
        if registry is None or operation is None:
            raise RuntimeError("provisioning_state_missing")
        registry.schema_name = schema
        registry.tenant_revision = current
        registry.state = "active"
        registry.feature_enabled = True
        registry.migration_error = None
        registry.updated_at = _now()
        operation.state = "succeeded"
        operation.last_error_code = None
        platform_db.commit()
        return registry
    except Exception as exc:
        platform_db.rollback()
        registry = platform_db.scalar(
            select(TenantRegistry).where(TenantRegistry.business_id == shop_id).with_for_update()
        )
        operation = platform_db.scalar(
            select(ProvisioningOperation).where(ProvisioningOperation.idempotency_key == key).with_for_update()
        )
        if registry is not None:
            registry.state = "error"
            registry.feature_enabled = False
            registry.migration_error = _error_code(exc)
            registry.updated_at = _now()
        if operation is not None:
            operation.state = "failed"
            operation.last_error_code = _error_code(exc)
        platform_db.commit()
        raise


__all__ = ["provision_shop"]
