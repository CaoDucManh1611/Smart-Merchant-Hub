"""Customer data export and privacy operations."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_access
from app.core.config import settings
from app.db.dependencies import get_db
from app.models.business import User
from app.models.saas import DataLifecycleRequest
from app.schemas.privacy import PrivacyDeleteRequest, PrivacyRequest, PrivacyRequestOut, PrivacyResponse
from app.services.audit_service import record_audit
from app.services.privacy_service import (
    anonymize_customer_data,
    complete_request,
    export_customer_data,
    get_or_create_request,
)
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context


router = APIRouter(prefix="/privacy")


@router.get("/requests", response_model=list[PrivacyRequestOut])
def list_lifecycle_requests(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    _actor: User | None = Depends(require_admin_access),
):
    """Expose an auditable lifecycle queue without returning customer payloads."""
    return db.query(DataLifecycleRequest).filter(
        DataLifecycleRequest.business_id == tenant.business_id,
    ).order_by(DataLifecycleRequest.created_at.desc(), DataLifecycleRequest.id.desc()).limit(200).all()


@router.get("/retention")
def retention_policy():
    return {
        "retention_days": max(1, int(settings.DATA_RETENTION_DAYS)),
        "accounting_records_retained": True,
        "customer_identifiers_redacted_on_delete": True,
    }


def _request_response(row, counts=None, data=None):
    metadata = row.result_metadata or {}
    return PrivacyResponse(
        id=row.id,
        kind=row.kind,
        status=row.status,
        counts=counts or metadata.get("counts", {}),
        data=data,
    )


@router.post("/export", response_model=PrivacyResponse)
def export_data(
    payload: PrivacyRequest,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_admin_access),
):
    try:
        row, created = get_or_create_request(db, business_id=tenant.business_id, request_key=payload.request_key, kind="export", requested_by=actor.id if actor else None)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not created and row.status == "completed":
        data, counts = export_customer_data(db, tenant.business_id)
        return _request_response(row, counts=counts, data=data)
    data, counts = export_customer_data(db, tenant.business_id)
    complete_request(row, counts=counts)
    record_audit(db, business_id=tenant.business_id, user_id=actor.id if actor else None, action="privacy_export", resource_type="data_lifecycle_request", resource_id=row.id, metadata={"counts": counts})
    db.commit()
    return _request_response(row, counts=counts, data=data)


@router.post("/anonymize", response_model=PrivacyResponse)
def anonymize_data(
    payload: PrivacyRequest,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_admin_access),
):
    try:
        row, created = get_or_create_request(db, business_id=tenant.business_id, request_key=payload.request_key, kind="anonymize", requested_by=actor.id if actor else None)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not created and row.status == "completed":
        return _request_response(row)
    counts = anonymize_customer_data(db, tenant.business_id)
    complete_request(row, counts=counts)
    record_audit(db, business_id=tenant.business_id, user_id=actor.id if actor else None, action="privacy_anonymize", resource_type="data_lifecycle_request", resource_id=row.id, metadata={"counts": counts})
    db.commit()
    return _request_response(row, counts=counts)


@router.post("/delete", response_model=PrivacyResponse)
def delete_data(
    payload: PrivacyDeleteRequest,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_admin_access),
):
    if payload.confirmation_token != "DELETE":
        raise HTTPException(status_code=422, detail="Cần confirmation_token=DELETE để xác nhận.")
    try:
        row, created = get_or_create_request(db, business_id=tenant.business_id, request_key=payload.request_key, kind="delete", requested_by=actor.id if actor else None)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not created and row.status == "completed":
        return _request_response(row)
    counts = anonymize_customer_data(db, tenant.business_id, deleted=True)
    complete_request(row, counts=counts)
    record_audit(db, business_id=tenant.business_id, user_id=actor.id if actor else None, action="privacy_delete", resource_type="data_lifecycle_request", resource_id=row.id, metadata={"counts": counts, "mode": "anonymized_retained_orders"})
    db.commit()
    return _request_response(row, counts=counts)
