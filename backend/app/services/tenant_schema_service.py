"""Pilot registry for the future schema-per-tenant CRM database.

The registry deliberately does not issue CREATE SCHEMA or move existing rows.
It records a deterministic target and an explicit rollout state so operators
can rehearse migrations without changing the current business_id boundary.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.business import Business
from app.models.saas import TenantSchemaRegistry, validate_tenant_schema_name


SCHEMA_STATES = {"proposed", "ready", "disabled"}


def expected_schema_name(business_id: int) -> str:
    return validate_tenant_schema_name(f"tenant_{int(business_id)}")


def get_registry(db: Session, business_id: int) -> TenantSchemaRegistry | None:
    return db.scalar(
        select(TenantSchemaRegistry).where(
            TenantSchemaRegistry.business_id == business_id,
        )
    )


def ensure_registry(db: Session, business_id: int) -> TenantSchemaRegistry:
    """Create or return the staged registry row for an existing shop."""
    business = db.get(Business, business_id)
    if business is None:
        raise LookupError("Shop không tồn tại.")
    row = get_registry(db, business_id)
    if row is not None:
        return row
    row = TenantSchemaRegistry(
        business_id=business_id,
        schema_name=expected_schema_name(business_id),
        state="proposed",
        feature_enabled=False,
    )
    db.add(row)
    db.flush()
    return row


def update_registry(
    db: Session,
    business_id: int,
    *,
    state: str | None = None,
    feature_enabled: bool | None = None,
) -> TenantSchemaRegistry:
    row = ensure_registry(db, business_id)
    target_state = state or row.state
    if target_state not in SCHEMA_STATES:
        raise ValueError("Trạng thái schema không hợp lệ.")
    target_enabled = row.feature_enabled if feature_enabled is None else feature_enabled
    if target_enabled and target_state != "ready":
        raise ValueError("Chỉ bật schema pilot khi trạng thái là ready.")
    if target_state == "disabled":
        target_enabled = False
    row.state = target_state
    row.feature_enabled = target_enabled
    db.flush()
    return row
