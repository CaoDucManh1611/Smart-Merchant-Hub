"""Explicit per-tenant capability provisioning for successful API test paths."""

import json

from app.models.business_setting import BusinessSetting


def enable_workspace_capabilities(db, business_id: int, *capabilities: str) -> None:
    """Persist only the capabilities the isolated test scenario exercises.

    This helper is deliberately opt-in; it does not change global test or runtime
    defaults. Capability-denial tests should not call it.
    """
    enabled = sorted({"CORE_CRM", *capabilities})
    value = json.dumps(
        {
            "config_schema_version": 2,
            "business_model": "RETAIL",
            "business_type": "retail",
            "industry_ids": [],
            "enabled_modules": [],
            "enabled_capabilities": enabled,
            "capability_source": "explicit",
            "recommendation_industry": "general_retail",
            "purchase_model_reference_industry": "general_retail",
        },
        separators=(",", ":"),
    )
    setting = db.query(BusinessSetting).filter_by(
        business_id=business_id,
        key="workspace_modules",
    ).first()
    if setting is None:
        db.add(BusinessSetting(business_id=business_id, key="workspace_modules", value=value))
    else:
        setting.value = value
    db.flush()
