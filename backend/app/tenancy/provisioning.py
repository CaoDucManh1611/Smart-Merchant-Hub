"""Retryable, idempotent tenant-schema provisioning saga.

Provisioning is deliberately driven from the control-plane database.  The
tenant schema is never dropped as a compensating action: an interrupted
migration is recorded as ``provision_failed`` and can be retried safely.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.tenant_session import tenant_engine
from app.models.platform_control import PlatformBusiness, ProvisioningOperation, TenantRegistry
from app.tenancy.migration_runner import current_tenant_revision, upgrade_tenant_schema
from app.tenancy.schema import schema_name_for


class ProvisioningValidationError(ValueError):
    """A caller supplied an invalid provisioning request."""


def _error_code(error: Exception) -> str:
    """Convert arbitrary migration failures to a stable, non-sensitive code."""

    name = type(error).__name__.strip().lower()
    if "timeout" in name or "timeout" in str(error).lower():
        return "tenant_migration_timeout"
    if "permission" in name or "permission" in str(error).lower():
        return "tenant_migration_permission_denied"
    if "connect" in name or "connect" in str(error).lower():
        return "tenant_database_unavailable"
    return "tenant_migration_failed"


def _existing_operation(db: Session, idempotency_key: str) -> ProvisioningOperation | None:
    return db.scalar(
        select(ProvisioningOperation).where(
            ProvisioningOperation.idempotency_key == idempotency_key,
        ).with_for_update()
    )


def _existing_registry(db: Session, business_id: int) -> TenantRegistry | None:
    return db.scalar(
        select(TenantRegistry).where(TenantRegistry.business_id == business_id).with_for_update()
    )


def provision_shop(
    platform_db: Session,
    *,
    business_id: int,
    idempotency_key: str,
    tenant_connect: Callable[[], object] | None = None,
) -> TenantRegistry:
    """Provision ``shop_<business_id>`` and return its registry state.

    ``tenant_connect`` is injectable for deterministic tests; production uses
    the configured tenant engine.  Replaying an idempotency key returns the
    original operation result and never creates a second schema or operation.
    """

    try:
        business_id = int(business_id)
    except (TypeError, ValueError) as exc:
        raise ProvisioningValidationError("business_id must be a positive integer") from exc
    key = str(idempotency_key or "").strip()
    if business_id <= 0:
        raise ProvisioningValidationError("business_id must be a positive integer")
    if not key or len(key) > 180:
        raise ProvisioningValidationError("idempotency_key is required and must be at most 180 characters")

    business = platform_db.scalar(
        select(PlatformBusiness).where(PlatformBusiness.id == business_id).with_for_update()
    )
    if business is None:
        raise LookupError("Shop không tồn tại trong platform database.")

    operation = _existing_operation(platform_db, key)
    registry = _existing_registry(platform_db, business_id)
    if operation is not None:
        # A key is immutable.  If the caller replays after a failure, keep the
        # same operation and retry it; successful operations are terminal.
        if operation.business_id != business_id:
            raise ProvisioningValidationError("idempotency_key đã được dùng cho shop khác")
        registry = registry or _existing_registry(platform_db, operation.business_id)
        if operation.state == "succeeded" and registry is not None:
            return registry
    else:
        operation = ProvisioningOperation(
            idempotency_key=key,
            business_id=business_id,
            state="queued",
            attempt_count=0,
        )
        platform_db.add(operation)

    if registry is None:
        registry = TenantRegistry(
            business_id=business_id,
            schema_name=schema_name_for(business_id),
            state="provisioning",
            feature_enabled=False,
        )
        platform_db.add(registry)
    elif registry.state == "active":
        operation.state = "succeeded"
        platform_db.commit()
        return registry

    operation.state = "running"
    operation.attempt_count = int(operation.attempt_count or 0) + 1
    registry.state = "provisioning"
    registry.feature_enabled = False
    registry.migration_error = None
    platform_db.flush()
    platform_db.commit()

    connect = tenant_connect or (lambda: tenant_engine.connect())
    try:
        # Production always uses the explicitly configured tenant engine.
        connection_context = connect()
        with connection_context as connection:
            revision = upgrade_tenant_schema(connection, registry.schema_name)
            if not revision or current_tenant_revision(connection, registry.schema_name) != revision:
                raise RuntimeError("tenant_revision_not_recorded")
    except Exception as exc:  # noqa: BLE001 - sanitize before persisting
        registry.state = "provision_failed"
        registry.feature_enabled = False
        registry.migration_error = _error_code(exc)
        operation.state = "failed"
        operation.last_error_code = registry.migration_error
        platform_db.commit()
        return registry

    registry.tenant_revision = str(revision)
    registry.state = "active"
    registry.feature_enabled = True
    registry.migration_error = None
    operation.state = "succeeded"
    operation.last_error_code = None
    platform_db.commit()
    return registry


def retry_provision_shop(
    platform_db: Session,
    *,
    business_id: int,
    idempotency_key: str,
    tenant_connect: Callable[[], object] | None = None,
) -> TenantRegistry:
    """Explicit retry entry point; it shares the same idempotent saga."""

    return provision_shop(
        platform_db,
        business_id=business_id,
        idempotency_key=idempotency_key,
        tenant_connect=tenant_connect,
    )
