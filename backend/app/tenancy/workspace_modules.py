"""Per-shop business profile and optional module settings."""

from __future__ import annotations

import json

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.models.business_setting import BusinessSetting
from app.tenancy.context import TenantContext
from app.tenancy.crm_session import get_tenant_db
from app.tenancy.dependencies import get_tenant_context


SETTING_KEY = "workspace_modules"
MODULES = {"retail", "appointments", "projects"}
PROFILES = {"retail", "services", "b2b", "mixed"}
RETAIL_RFM_PRIOR_INDUSTRIES = {"general_retail", "fashion", "grocery", "ecommerce"}
DEFAULT_CONFIG = {
    "business_type": "retail",
    "enabled_modules": ["retail"],
    "recommendation_industry": "general_retail",
}


def _default_rfm_industry(business_type: str) -> str:
    return {
        "retail": "general_retail",
        "services": "services",
        "b2b": "b2b",
        "mixed": "mixed",
    }.get(business_type, "general_retail")


def get_workspace_config(db: Session, business_id: int) -> dict:
    setting = db.query(BusinessSetting).filter(
        BusinessSetting.business_id == business_id,
        BusinessSetting.key == SETTING_KEY,
    ).first()
    try:
        config = json.loads(setting.value) if setting else DEFAULT_CONFIG
    except (TypeError, json.JSONDecodeError):
        config = DEFAULT_CONFIG
    if not isinstance(config, dict):
        config = DEFAULT_CONFIG
    profile = config.get("business_type")
    enabled = config.get("enabled_modules")
    normalized_profile = profile if isinstance(profile, str) and profile in PROFILES else DEFAULT_CONFIG["business_type"]
    recommendation_industry = config.get("recommendation_industry")
    if normalized_profile == "retail":
        valid_industry = recommendation_industry in RETAIL_RFM_PRIOR_INDUSTRIES
    else:
        valid_industry = recommendation_industry == normalized_profile
    return {
        "business_type": normalized_profile,
        "enabled_modules": [module for module in enabled if isinstance(module, str) and module in MODULES]
        if isinstance(enabled, list)
        else DEFAULT_CONFIG["enabled_modules"],
        "recommendation_industry": recommendation_industry if valid_industry else _default_rfm_industry(normalized_profile),
    }


def save_workspace_config(db: Session, business_id: int, config: dict) -> dict:
    business_type = config["business_type"]
    requested_industry = config.get("recommendation_industry")
    valid_industry = (
        requested_industry in RETAIL_RFM_PRIOR_INDUSTRIES
        if business_type == "retail"
        else requested_industry == business_type
    )
    normalized = {
        "business_type": business_type,
        "enabled_modules": sorted(set(config["enabled_modules"]) & MODULES),
        "recommendation_industry": requested_industry if valid_industry else _default_rfm_industry(business_type),
    }
    value = json.dumps(normalized, separators=(",", ":"))
    setting = db.query(BusinessSetting).filter(
        BusinessSetting.business_id == business_id,
        BusinessSetting.key == SETTING_KEY,
    ).first()
    if setting is None:
        db.add(BusinessSetting(business_id=business_id, key=SETTING_KEY, value=value))
    else:
        setting.value = value
    return normalized


def require_module_enabled(module: str):
    """Protect every route in an optional module, including direct API calls."""

    def dependency(
        db: Session = Depends(get_tenant_db),
        tenant: TenantContext = Depends(get_tenant_context),
    ) -> None:
        if module not in get_workspace_config(db, tenant.business_id)["enabled_modules"]:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "workspace_module_disabled",
                    "module": module,
                    "message": "Bộ chức năng này đang tắt trong Cài đặt của shop.",
                },
            )

    return dependency
