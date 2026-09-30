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
DEFAULT_CONFIG = {"business_type": "retail", "enabled_modules": ["retail"]}


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
    return {
        "business_type": profile if isinstance(profile, str) and profile in PROFILES else DEFAULT_CONFIG["business_type"],
        "enabled_modules": [module for module in enabled if isinstance(module, str) and module in MODULES]
        if isinstance(enabled, list)
        else DEFAULT_CONFIG["enabled_modules"],
    }


def save_workspace_config(db: Session, business_id: int, config: dict) -> dict:
    normalized = {
        "business_type": config["business_type"],
        "enabled_modules": sorted(set(config["enabled_modules"]) & MODULES),
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
