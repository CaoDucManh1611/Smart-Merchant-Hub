"""Redacted, append-only audit writer."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


REDACTED_KEYS = {"password", "password_hash", "token", "access_token", "secret", "content", "body"}


def _redact(value):
    if isinstance(value, Mapping):
        return {str(key): ("[REDACTED]" if str(key).lower() in REDACTED_KEYS else _redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def record_audit(
    db: Session,
    *,
    business_id: int,
    action: str,
    resource_type: str,
    resource_id: str | int | None = None,
    user_id: int | None = None,
    metadata: Mapping | None = None,
) -> AuditLog:
    row = AuditLog(
        business_id=business_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        metadata_=_redact(dict(metadata or {})),
    )
    db.add(row)
    return row
