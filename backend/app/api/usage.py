"""Tenant-visible entitlements and usage warnings."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_optional_user
from app.database.platform_session import get_platform_db
from app.models.business import User
from app.schemas.onboarding import QuotaSnapshotOut
from app.services.quota_service import quota_snapshot
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context


router = APIRouter(prefix="/usage")


@router.get("", response_model=QuotaSnapshotOut)
def get_usage(
    db: Session = Depends(get_platform_db),
    tenant: TenantContext = Depends(get_tenant_context),
    _user: User | None = Depends(get_optional_user),
):
    return quota_snapshot(db, tenant.business_id)


@router.get("/warnings")
def get_usage_warnings(
    db: Session = Depends(get_platform_db),
    tenant: TenantContext = Depends(get_tenant_context),
    _user: User | None = Depends(get_optional_user),
):
    snapshot = quota_snapshot(db, tenant.business_id)
    return {
        "business_id": snapshot["business_id"],
        "period_start": snapshot["period_start"],
        "warning_percent": snapshot["warning_percent"],
        "items": [
            {"resource": resource, **details}
            for resource, details in snapshot["resources"].items()
            if details["near_limit"]
        ],
    }
