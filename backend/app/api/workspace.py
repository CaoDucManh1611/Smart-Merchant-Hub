"""Shop-specific business profile and module configuration."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_access
from app.models.crm_workspace_config import CrmWorkspaceConfig
from app.models.customer import Customer
from app.models.lead import Lead
from app.schemas.crm_config import CrmWorkspaceConfigUpdate
from app.services.audit_service import record_audit
from app.services.crm_workspace_config import get_crm_workspace_config, validate_customer_custom_fields
from app.models.business import User
from app.tenancy.context import TenantContext
from app.tenancy.crm_session import get_tenant_db
from app.tenancy.dependencies import get_tenant_context
from app.tenancy.workspace_modules import get_workspace_config, save_workspace_config


router = APIRouter(prefix="/workspace")


class WorkspaceModulesUpdate(BaseModel):
    business_type: Literal["retail", "services", "b2b", "mixed"]
    enabled_modules: list[Literal["retail", "appointments", "projects"]] = Field(max_length=3)


@router.get("/modules")
def read_modules(
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    config = get_workspace_config(db, tenant.business_id)
    return {
        **config,
        "modules": [
            {"id": "core", "name": "Lõi CRM", "available": True, "enabled": True},
            {"id": "retail", "name": "Bán lẻ", "available": True, "enabled": "retail" in config["enabled_modules"]},
            {"id": "appointments", "name": "Dịch vụ theo lịch", "available": True, "enabled": "appointments" in config["enabled_modules"]},
            {"id": "projects", "name": "Báo giá / dự án", "available": True, "enabled": "projects" in config["enabled_modules"]},
        ],
    }


@router.put("/modules")
def update_modules(
    payload: WorkspaceModulesUpdate,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    _actor: User | None = Depends(require_admin_access),
):
    config = save_workspace_config(db, tenant.business_id, {
        "business_type": payload.business_type,
        "enabled_modules": payload.enabled_modules,
    })
    db.commit()
    return config


@router.get("/crm-config")
def read_crm_config(
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    return get_crm_workspace_config(db, tenant.business_id)


@router.put("/crm-config")
def update_crm_config(
    payload: CrmWorkspaceConfigUpdate,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_admin_access),
):
    current = get_crm_workspace_config(db, tenant.business_id)
    updated = payload.model_dump()
    old_stages = {stage["key"] for stage in current["pipeline_stages"]}
    new_stages = {stage.key for stage in payload.pipeline_stages}
    removed_stages = old_stages - new_stages
    if removed_stages:
        used = db.query(Lead.id).filter(
            Lead.business_id == tenant.business_id,
            Lead.stage.in_(removed_stages),
        ).first()
        if used:
            raise HTTPException(status_code=409, detail="Không thể bỏ giai đoạn đang có cơ hội. Hãy chuyển các cơ hội sang giai đoạn khác trước.")

    definitions = [field.model_dump() for field in payload.customer_fields]
    for customer in db.query(Customer).filter(Customer.business_id == tenant.business_id).all():
        try:
            validate_customer_custom_fields(customer.custom_fields or {}, definitions)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=f"Không thể đổi cấu hình vì dữ liệu khách hàng chưa tương thích: {exc}") from exc
    updated["customer_fields"] = definitions
    updated["pipeline_stages"] = [stage.model_dump() for stage in payload.pipeline_stages]

    row = db.query(CrmWorkspaceConfig).filter(CrmWorkspaceConfig.business_id == tenant.business_id).first()
    if row is None:
        row = CrmWorkspaceConfig(business_id=tenant.business_id, **updated)
        db.add(row)
    else:
        row.customer_fields = updated["customer_fields"]
        row.pipeline_stages = updated["pipeline_stages"]
    db.flush()
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="crm_workspace_config_updated",
        resource_type="crm_workspace_config",
        resource_id=row.id,
        metadata={"customer_field_count": len(definitions), "pipeline_stage_count": len(updated["pipeline_stages"])},
    )
    db.commit()
    return updated
