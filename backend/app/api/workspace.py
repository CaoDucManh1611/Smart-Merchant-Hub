"""Shop-specific business profile and module configuration."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_access
from app.models.crm_workspace_config import CrmWorkspaceConfig
from app.models.customer import Customer
from app.models.lead import Lead
from app.schemas.crm_config import CrmWorkspaceConfigUpdate
from app.services.audit_service import record_audit
from app.services.crm_workspace_config import get_crm_workspace_config, validate_customer_custom_fields
from app.services.shop_otp_email import (
    _EMAIL_RE,
    claim_shop_test_email_slot,
    get_shop_otp_smtp_config,
    read_shop_otp_email,
    save_shop_otp_email,
)
from app.services.otp_delivery import OtpDeliveryError, OtpDeliveryNotConfigured, send_smtp_test_email
from app.services.shop_bank_transfer import (
    BankTransferSettingsUpdate,
    read_shop_bank_transfer,
    save_shop_bank_transfer,
    validate_shop_bank_transfer,
)
from app.services.industry_rfm_prior import industry_rfm_prior_status
from app.services.capability_registry import (
    BUSINESS_MODEL_TO_LEGACY,
    CAPABILITY_IDS,
    CAPABILITY_REGISTRY,
    CAPABILITY_REGISTRY_VERSION,
)
from app.models.business import User
from app.tenancy.context import TenantContext
from app.tenancy.crm_session import get_tenant_db
from app.tenancy.dependencies import get_tenant_context
from app.tenancy.workspace_modules import get_workspace_config, save_workspace_config


router = APIRouter(prefix="/workspace")


class WorkspaceModulesUpdate(BaseModel):
    business_type: Literal["retail", "services", "b2b", "mixed"] | None = None
    business_model: Literal["RETAIL", "APPOINTMENT_SERVICE", "PROJECT_B2B", "MULTI_SERVICE"] | None = None
    enabled_modules: list[Literal["retail", "appointments", "projects"]] | None = Field(default=None, max_length=3)
    enabled_capabilities: list[Literal[
        "CORE_CRM", "RETAIL_TOOLS", "APPOINTMENT_TOOLS", "PROJECT_QUOTATION_TOOLS",
        "INVENTORY_TOOLS", "ORDER_TOOLS", "CUSTOMER_TOOLS", "RENTAL_TOOLS",
        "PAYMENT_TOOLS", "RECOMMENDATION_TOOLS",
    ]] | None = Field(default=None, max_length=10)
    industry_ids: list[Literal[
        "fashion_apparel", "beauty_cosmetics", "electronics", "automotive_motorbike",
        "furniture_home_living", "food_beverage", "real_estate", "education",
        "travel_hospitality", "healthcare_wellness", "b2b_wholesale", "services_repair",
        "rental_business", "professional_services",
    ]] | None = Field(default=None, max_length=14)
    purchase_model_reference_industry: Literal[
        "general_retail", "fashion", "grocery", "ecommerce", "services", "b2b", "mixed",
    ] | None = None
    recommendation_industry: Literal[
        "general_retail", "fashion", "grocery", "ecommerce", "services", "b2b", "mixed",
    ] | None = None

    @model_validator(mode="after")
    def validate_business_model_present(self):
        if self.business_model is None and self.business_type is None:
            raise ValueError("Cần chọn mô hình kinh doanh.")
        if self.enabled_modules is None and self.enabled_capabilities is None:
            raise ValueError("Cần gửi cấu hình capability hoặc module tương thích.")
        if self.industry_ids is not None and len(set(self.industry_ids)) != len(self.industry_ids):
            raise ValueError("Không chọn trùng ngành.")
        if self.enabled_capabilities is not None and len(set(self.enabled_capabilities)) != len(self.enabled_capabilities):
            raise ValueError("Không chọn trùng capability.")
        return self


class ShopOtpEmailUpdate(BaseModel):
    enabled: bool = False
    host: str = Field(default="smtp.gmail.com", max_length=255)
    port: int = Field(default=587, ge=1, le=65535)
    security: Literal["starttls", "ssl"] = "starttls"
    username: str = Field(default="", max_length=255)
    password: str = Field(default="", max_length=200)
    from_email: str = Field(default="", max_length=255)
    from_name: str = Field(default="", max_length=120)


class ShopOtpEmailTest(BaseModel):
    email: str = Field(min_length=3, max_length=255)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL_RE.fullmatch(value):
            raise ValueError("Email nhận thử không hợp lệ.")
        return value


@router.get("/bank-transfer")
def read_bank_transfer_settings(
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    _actor: User | None = Depends(require_admin_access),
):
    return read_shop_bank_transfer(db, tenant.business_id)


@router.put("/bank-transfer")
def update_bank_transfer_settings(
    payload: BankTransferSettingsUpdate,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_admin_access),
):
    try:
        result = save_shop_bank_transfer(db, tenant.business_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="shop_bank_transfer_settings_updated",
        resource_type="business_setting",
        resource_id="shop.bank_transfer",
        metadata={
            "enabled": bool(result["enabled"]),
            "bank_bin": result["bank_bin"],
            "account_last4": str(result["account_number"] or "")[-4:],
        },
    )
    db.commit()
    return result


@router.post("/bank-transfer/validate")
def validate_bank_transfer_settings(
    payload: BankTransferSettingsUpdate,
    _db: Session = Depends(get_tenant_db),
    _tenant: TenantContext = Depends(get_tenant_context),
    _actor: User | None = Depends(require_admin_access),
):
    try:
        return validate_shop_bank_transfer(payload)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.get("/otp-email")
def read_otp_email_settings(
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    _actor: User | None = Depends(require_admin_access),
):
    return read_shop_otp_email(db, tenant.business_id)


@router.put("/otp-email")
def update_otp_email_settings(
    payload: ShopOtpEmailUpdate,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_admin_access),
):
    try:
        result = save_shop_otp_email(db, tenant.business_id, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="shop_otp_email_updated",
        resource_type="business_setting",
        resource_id="otp.smtp",
        metadata={"enabled": bool(result["enabled"]), "from_email": result["from_email"]},
    )
    db.commit()
    return result


@router.post("/otp-email/test")
def test_shop_otp_email(
    payload: ShopOtpEmailTest,
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
    actor: User | None = Depends(require_admin_access),
):
    try:
        config = get_shop_otp_smtp_config(db, tenant.business_id)
        if config is None:
            raise OtpDeliveryNotConfigured("Shop SMTP is disabled")
        if not claim_shop_test_email_slot(db, tenant.business_id):
            raise HTTPException(429, "Vui lòng chờ 60 giây trước khi gửi email thử tiếp theo.", headers={"Retry-After": "60"})
        send_smtp_test_email(destination=payload.email, smtp_config=config)
    except HTTPException:
        raise
    except (OtpDeliveryError, OtpDeliveryNotConfigured, ValueError, OSError, SQLAlchemyError) as error:
        raise HTTPException(503, "Chưa gửi được email thử. Kiểm tra cấu hình SMTP đã lưu và kết nối rồi thử lại.") from error
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="shop_otp_email_test",
        resource_type="business_setting",
        resource_id="otp.smtp",
        metadata={"status": "smtp_accepted"},
    )
    db.commit()
    return {"status": "smtp_accepted", "email": payload.email}


@router.get("/modules")
def read_modules(
    db: Session = Depends(get_tenant_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    config = get_workspace_config(db, tenant.business_id)
    from app.services.universal_sales_brain import VERTICAL_PLAYBOOKS
    prior = industry_rfm_prior_status()
    prior.update({
        "kind": "rfm_segment_prior",
        "selected_industry": config["recommendation_industry"],
        "shop_segment_minimum_consented_buyers": 20,
        "shop_model_minimum_consented_buyers": 20,  # compatibility alias; this is not a propensity threshold
        "shop_specific_algorithm": "MiniBatchKMeans RFM segmentation",
        "threshold_purpose": "Minimum consented buyers for the existing shop-specific RFM segmentation branch; not a propensity-model or ranker quality guarantee.",
    })
    return {
        **config,
        "rfm_model": prior,
        "purchase_propensity_model": {
            "available": False,
            "kind": None,
            "reason": "Repository code contains RFM scoring/segmentation and recommendation ranking, but no separately trained purchase-probability model with labels, inference contract, and evaluation evidence.",
        },
        "recommendation_model": {
            "kind": "ranking",
            "code_available": True,
            "lightfm_algorithm": "lightfm_warp_rfm_v2",
            "is_purchase_propensity": False,
            "detail": "LightFM is an optional candidate ranker after retrieval; it does not produce a purchase probability.",
        },
        "capability_registry_version": CAPABILITY_REGISTRY_VERSION,
        "capability_registry": [
            {"capability_id": key, **value}
            for key, value in CAPABILITY_REGISTRY.items()
        ],
        "industry_profiles": [
            {
                "industry_id": profile.industry_id,
                "industry_name": profile.industry_name,
                "business_characteristics": list(profile.selection_criteria),
                "customer_information_requirements": [slot.model_dump(mode="json") for slot in profile.required_customer_information],
                "recommendation_strategy": list(profile.recommendation_rules),
                "applicable_workflows": list(profile.available_workflows),
                "guardrails": list(profile.prohibited_assumptions),
                "playbook_version": profile.playbook_version,
            }
            for profile in VERTICAL_PLAYBOOKS.values()
        ],
        "purchase_model_reference_options": [
            {"id": value, "name": name, "type": "rfm_segment_reference_profile"}
            for value, name in (
                ("general_retail", "Bán lẻ tổng hợp"),
                ("fashion", "Thời trang"),
                ("grocery", "Thực phẩm & hàng tiêu dùng"),
                ("ecommerce", "Thương mại điện tử"),
                ("services", "Dịch vụ (profile tổng hợp)"),
                ("b2b", "B2B (profile tổng hợp)"),
                ("mixed", "Đa dịch vụ (profile tổng hợp)"),
            )
        ],
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
    actor: User | None = Depends(require_admin_access),
):
    reference = payload.purchase_model_reference_industry or payload.recommendation_industry
    current = get_workspace_config(db, tenant.business_id)
    model_by_legacy = {legacy: model for model, legacy in BUSINESS_MODEL_TO_LEGACY.items()}
    selected_model = (
        payload.business_model
        or model_by_legacy.get(payload.business_type)
        or current["business_model"]
    )
    if payload.enabled_capabilities is not None:
        selected_capabilities = payload.enabled_capabilities
    elif payload.enabled_modules is None:
        # A model/industry-only update must not expand or reduce existing grants.
        selected_capabilities = current["enabled_capabilities"]
    else:
        # Compatibility for older clients that only submit bundled modules.
        selected_capabilities = None
    try:
        config = save_workspace_config(db, tenant.business_id, {
            "business_type": payload.business_type or BUSINESS_MODEL_TO_LEGACY[selected_model],
            "business_model": selected_model,
            "enabled_modules": payload.enabled_modules if payload.enabled_modules is not None else current["enabled_modules"],
            "enabled_capabilities": selected_capabilities,
            "legacy_module_update": payload.enabled_capabilities is None and payload.enabled_modules is not None,
            "industry_ids": payload.industry_ids if payload.industry_ids is not None else current["industry_ids"],
            "purchase_model_reference_industry": reference or current["purchase_model_reference_industry"],
        })
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_audit(
        db,
        business_id=tenant.business_id,
        user_id=actor.id if actor else None,
        action="shop_business_capabilities_updated",
        resource_type="business_setting",
        resource_id="workspace_modules",
        metadata={
            "config_version": config["config_version"],
            "business_model": config["business_model"],
            "industry_count": len(config["industry_ids"]),
            "enabled_capabilities": config["enabled_capabilities"],
            "capability_source": config["capability_source"],
        },
    )
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
