"""Per-tenant business model, industry, capability and RFM reference settings."""

from __future__ import annotations

import json
import re

from fastapi import Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.business_setting import BusinessSetting
from app.services.capability_registry import (
    BUSINESS_MODEL_TO_LEGACY,
    CAPABILITY_IDS,
    CAPABILITY_REGISTRY_VERSION,
    DEFAULT_CAPABILITIES,
    LEGACY_TO_BUSINESS_MODEL,
    SUPPORTED_DEPENDENCIES,
    capability_activation_issues,
    capability_details,
    enabled_capabilities,
    legacy_capabilities,
)
from app.tenancy.context import TenantContext
from app.tenancy.crm_session import get_tenant_db
from app.tenancy.dependencies import get_tenant_context


SETTING_KEY = "workspace_modules"
PAYMENT_CONFIGURATION_KEYS = {
    "shop.bank_transfer.enabled",
    "shop.bank_transfer.bank_bin",
    "shop.bank_transfer.account_number_encrypted",
    "shop.bank_transfer.account_name",
}
MODULES = {"retail", "appointments", "projects"}
PROFILES = set(LEGACY_TO_BUSINESS_MODEL)
BUSINESS_MODELS = set(BUSINESS_MODEL_TO_LEGACY)
RETAIL_RFM_PRIOR_INDUSTRIES = {"general_retail", "fashion", "grocery", "ecommerce"}
RFM_REFERENCE_INDUSTRIES = RETAIL_RFM_PRIOR_INDUSTRIES | {"services", "b2b", "mixed"}
DEFAULT_CONFIG = {
    "business_type": "retail",
    "business_model": "RETAIL",
    # A brand-new tenant receives the always-on CRM core only. Legacy saved
    # module lists are still mapped below as pre-existing explicit grants.
    "enabled_modules": [],
    "enabled_capabilities": ["CORE_CRM"],
    "industry_ids": [],
    "recommendation_industry": "general_retail",
}


def _default_rfm_industry(business_type: str) -> str:
    return {
        "retail": "general_retail",
        "services": "services",
        "b2b": "b2b",
        "mixed": "mixed",
    }.get(business_type, "general_retail")


def _industry_ids() -> set[str]:
    from app.services.universal_sales_brain import VERTICAL_PLAYBOOKS
    return set(VERTICAL_PLAYBOOKS)


def _safe_empty_config(*, rejected: bool = False) -> dict:
    """Corrupt configuration never grants optional tools by default."""
    return {
        "business_type": "retail",
        "business_model": "RETAIL",
        "enabled_modules": [],
        "enabled_capabilities": list(DEFAULT_CAPABILITIES),
        "explicitly_enabled_capabilities": [],
        "default_capabilities": list(DEFAULT_CAPABILITIES),
        "capability_source": "invalid_configuration" if rejected else "default",
        "capability_registry_version": CAPABILITY_REGISTRY_VERSION,
        "industry_ids": [],
        "recommendation_industry": "general_retail",
        "purchase_model_reference_industry": "general_retail",
        "config_version": 1,
        "configuration_rejected": rejected,
    }


def _normalized_config(raw: object, *, missing_row: bool = False) -> dict:
    if not isinstance(raw, dict):
        return _safe_empty_config(rejected=True)
    if missing_row:
        raw = DEFAULT_CONFIG
    legacy_model = raw.get("business_type")
    selected_model = raw.get("business_model")
    if selected_model not in BUSINESS_MODELS:
        selected_model = LEGACY_TO_BUSINESS_MODEL.get(legacy_model, "RETAIL")
    business_type = BUSINESS_MODEL_TO_LEGACY[selected_model]

    modules = raw.get("enabled_modules")
    if not isinstance(modules, list) or any(not isinstance(module, str) for module in modules):
        if missing_row:
            modules = list(DEFAULT_CONFIG["enabled_modules"])
        else:
            return _safe_empty_config(rejected=True)
    if len(set(modules) - MODULES):
        return _safe_empty_config(rejected=True)
    modules = sorted(set(modules))

    raw_caps = raw.get("enabled_capabilities")
    explicit_caps: list[str] = []
    if raw_caps is None:
        caps = list(legacy_capabilities(modules))
        capability_source = "legacy_workspace_modules" if not missing_row else "default_workspace_modules"
    elif isinstance(raw_caps, list) and all(isinstance(value, str) and value in CAPABILITY_IDS for value in raw_caps):
        explicit_caps = [] if missing_row else sorted(set(raw_caps) - {"CORE_CRM"})
        caps = sorted(set(raw_caps) | {"CORE_CRM"}, key=CAPABILITY_IDS.index)
        capability_source = "default" if missing_row else "explicit"
    else:
        return _safe_empty_config(rejected=True)

    industries = raw.get("industry_ids", [])
    if not isinstance(industries, list) or any(not isinstance(value, str) for value in industries):
        return _safe_empty_config(rejected=True)
    valid_industries = _industry_ids()
    if len(set(industries)) != len(industries) or any(value not in valid_industries for value in industries):
        return _safe_empty_config(rejected=True)
    industries = list(industries)

    reference = raw.get("purchase_model_reference_industry", raw.get("recommendation_industry"))
    if reference not in RFM_REFERENCE_INDUSTRIES:
        reference = _default_rfm_industry(business_type)

    if raw_caps is not None:
        caps_set = set(caps)
        modules = []
        if caps_set & {"RETAIL_TOOLS", "INVENTORY_TOOLS", "ORDER_TOOLS", "PAYMENT_TOOLS", "RECOMMENDATION_TOOLS"}:
            modules.append("retail")
        if "APPOINTMENT_TOOLS" in caps_set:
            modules.append("appointments")
        if "PROJECT_QUOTATION_TOOLS" in caps_set:
            modules.append("projects")
        modules.sort()

    try:
        config_version = max(1, int(raw.get("config_version", 1)))
    except (ValueError, TypeError, OverflowError):
        config_version = 1
    return {
        "business_type": business_type,
        "business_model": selected_model,
        "enabled_modules": modules,
        "enabled_capabilities": caps,
        "explicitly_enabled_capabilities": explicit_caps,
        "default_capabilities": list(DEFAULT_CAPABILITIES),
        "capability_source": capability_source,
        "capability_registry_version": CAPABILITY_REGISTRY_VERSION,
        "industry_ids": industries,
        "recommendation_industry": reference,
        "purchase_model_reference_industry": reference,
        "config_version": config_version,
        "configuration_rejected": False,
    }


def available_dependencies_for_tenant(db: Session, business_id: int) -> frozenset[str]:
    """Return code integrations plus tenant-owned configuration that is ready.

    Payment service code is deployed with the app, but payment configuration is
    shop-specific. It is available only after the shop has enabled and stored a
    complete bank-transfer recipient. Missing or malformed settings fail closed.
    """
    available = set(SUPPORTED_DEPENDENCIES)
    try:
        rows = db.query(BusinessSetting).filter(
            BusinessSetting.business_id == business_id,
            BusinessSetting.key.in_(PAYMENT_CONFIGURATION_KEYS),
        ).all()
        values = {row.key: row.value for row in rows}
    except (SQLAlchemyError, TypeError, AttributeError):
        # Payment readiness is tenant data. If it cannot be read, keep the
        # integration unavailable instead of treating a failed lookup as ready.
        values = {}
    payment_ready = False
    encrypted_account = values.get("shop.bank_transfer.account_number_encrypted", "")
    if (
        values.get("shop.bank_transfer.enabled") == "true"
        and values.get("shop.bank_transfer.bank_bin", "").strip()
        and encrypted_account.strip()
        and values.get("shop.bank_transfer.account_name", "").strip()
    ):
        try:
            from app.core.config import settings
            from app.services.channel_credentials import decrypt_token
            from app.services.vietnam_banks import BANKS

            account_number = decrypt_token(
                encrypted_account, settings.CHANNEL_ENCRYPTION_KEY,
            ).strip()
            payment_ready = (
                values["shop.bank_transfer.bank_bin"] in BANKS
                and account_number.isascii()
                and account_number.isdigit()
                and 6 <= len(account_number) <= 34
            )
        except Exception:
            # Corrupt ciphertext or unavailable encryption configuration must
            # never make this shop appear payment-ready.
            payment_ready = False
    if payment_ready:
        available.add("payment_configuration")
    else:
        available.discard("payment_configuration")
    return frozenset(available)


def get_workspace_config(db: Session, business_id: int) -> dict:
    setting = db.query(BusinessSetting).filter(
        BusinessSetting.business_id == business_id,
        BusinessSetting.key == SETTING_KEY,
    ).first()
    if setting is None:
        config = _normalized_config(DEFAULT_CONFIG, missing_row=True)
    else:
        try:
            raw = json.loads(setting.value)
        except (TypeError, json.JSONDecodeError):
            raw = None
        config = _normalized_config(raw)
    available_dependencies = available_dependencies_for_tenant(db, business_id)
    config["available_dependencies"] = sorted(available_dependencies)
    config["capabilities"] = capability_details(config, available_dependencies=available_dependencies)
    return config


def save_workspace_config(db: Session, business_id: int, config: dict) -> dict:
    current_row = db.query(BusinessSetting).filter(
        BusinessSetting.business_id == business_id,
        BusinessSetting.key == SETTING_KEY,
    ).first()
    current_raw = {}
    if current_row is not None:
        try:
            current_raw = json.loads(current_row.value)
        except (TypeError, json.JSONDecodeError):
            current_raw = {}

    selected_model = config.get("business_model")
    business_type = config.get("business_type") or current_raw.get("business_type") or "retail"
    if selected_model not in BUSINESS_MODELS:
        selected_model = LEGACY_TO_BUSINESS_MODEL.get(business_type, "RETAIL")
    business_type = BUSINESS_MODEL_TO_LEGACY[selected_model]

    modules = config.get("enabled_modules", current_raw.get("enabled_modules", DEFAULT_CONFIG["enabled_modules"]))
    if not isinstance(modules, list) or any(not isinstance(module, str) for module in modules):
        raise ValueError("Danh sách module không hợp lệ.")
    if len(set(modules) - MODULES):
        raise ValueError("Danh sách module không hợp lệ.")
    modules = sorted(set(modules))

    requested_caps = config.get("enabled_capabilities")
    if requested_caps is None:
        legacy_module_update = bool(config.get("legacy_module_update"))
        stored_caps = current_raw.get("enabled_capabilities")
        if not legacy_module_update and isinstance(stored_caps, list) and all(
            isinstance(value, str) and value in CAPABILITY_IDS for value in stored_caps
        ):
            raw_caps = sorted(set(stored_caps) | {"CORE_CRM"}, key=CAPABILITY_IDS.index)
            capability_source = "explicit"
        elif current_row is None and not legacy_module_update:
            raw_caps = list(DEFAULT_CAPABILITIES)
            capability_source = "default"
        else:
            raw_caps = None
            capability_source = "legacy_workspace_modules"
    else:
        if not isinstance(requested_caps, (list, tuple)) or any(
            not isinstance(value, str) or value not in CAPABILITY_IDS for value in requested_caps
        ):
            raise ValueError("Danh sách capability không hợp lệ.")
        raw_caps = sorted(set(requested_caps) | {"CORE_CRM"}, key=CAPABILITY_IDS.index)
        capability_source = "explicit"
        available_dependencies = available_dependencies_for_tenant(db, business_id)
        activation_issues = capability_activation_issues(
            raw_caps,
            available_dependencies=available_dependencies,
        )
        if activation_issues:
            details = "; ".join(
                f"{capability}: {', '.join(missing)}"
                for capability, missing in sorted(activation_issues.items())
            )
            raise ValueError(f"Chưa thể bật capability do thiếu phụ thuộc: {details}.")

    industries = config.get("industry_ids", current_raw.get("industry_ids", []))
    if not isinstance(industries, list) or any(not isinstance(value, str) for value in industries):
        raise ValueError("Danh sách ngành không hợp lệ.")
    valid_industries = _industry_ids()
    if len(set(industries)) != len(industries) or any(value not in valid_industries for value in industries):
        raise ValueError("Ngành cấu hình không nằm trong danh mục Industry Profile.")

    reference = config.get("purchase_model_reference_industry", config.get("recommendation_industry"))
    if reference is None:
        reference = current_raw.get(
            "purchase_model_reference_industry",
            current_raw.get("recommendation_industry", _default_rfm_industry(business_type)),
        )
    if reference not in RFM_REFERENCE_INDUSTRIES:
        raise ValueError("Ngành tham chiếu RFM không hợp lệ.")

    normalized_raw = {
        "config_schema_version": 2,
        "business_model": selected_model,
        "business_type": business_type,
        "industry_ids": list(industries),
        "enabled_modules": modules,
        "recommendation_industry": reference,
        "purchase_model_reference_industry": reference,
        "capability_source": capability_source,
    }
    if raw_caps is not None:
        normalized_raw["enabled_capabilities"] = raw_caps

    before = {key: current_raw.get(key) for key in normalized_raw if key != "config_version"}
    if before == normalized_raw:
        try:
            version = max(1, int(current_raw.get("config_version", 1)))
        except (ValueError, TypeError, OverflowError):
            version = 1
    else:
        try:
            version = max(1, int(current_raw.get("config_version", 0))) + 1
        except (ValueError, TypeError, OverflowError):
            version = 1
    normalized_raw["config_version"] = version
    value = json.dumps(normalized_raw, separators=(",", ":"), ensure_ascii=False)
    if current_row is None:
        db.add(BusinessSetting(business_id=business_id, key=SETTING_KEY, value=value))
    else:
        current_row.value = value
    result = _normalized_config(normalized_raw)
    available_dependencies = available_dependencies_for_tenant(db, business_id)
    result["available_dependencies"] = sorted(available_dependencies)
    result["capabilities"] = capability_details(result, available_dependencies=available_dependencies)
    return result


def _required_capabilities_for_module(module: str, path: str) -> tuple[str, ...]:
    normalized = path.casefold()
    if module == "recommendations":
        return ("RECOMMENDATION_TOOLS", "RETAIL_TOOLS")
    if module == "appointments":
        return ("APPOINTMENT_TOOLS",)
    if module == "projects":
        return ("PROJECT_QUOTATION_TOOLS",)
    if module == "retail":
        if "/inventory" in normalized:
            return ("RETAIL_TOOLS", "INVENTORY_TOOLS")
        if "/purchase-orders" in normalized or "/suppliers" in normalized:
            return ("INVENTORY_TOOLS",)
        if "/payments" in normalized or "/payment" in normalized:
            return ("PAYMENT_TOOLS",)
        if "/orders" in normalized or "/order" in normalized:
            return ("RETAIL_TOOLS", "ORDER_TOOLS")
        return ("RETAIL_TOOLS",)
    return ()


def require_module_enabled(module: str):
    """Enforce capability permissions at API boundaries.

    Read-only history remains accessible after a capability is disabled. Live
    catalogs and new transaction/workflow writes require the corresponding
    capability. A narrowly scoped edit to an existing order/appointment may
    continue; this never permits submit/transition/payment-request actions.
    """
    def dependency(
        request: Request,
        db: Session = Depends(get_tenant_db),
        tenant: TenantContext = Depends(get_tenant_context),
    ) -> None:
        config = get_workspace_config(db, tenant.business_id)
        required = _required_capabilities_for_module(module, request.url.path)
        active = set(enabled_capabilities(config))
        enabled = bool(required and set(required).issubset(active))
        if enabled:
            return
        method = request.method.upper()
        path = request.url.path.casefold().rstrip("/") or "/"
        history_roots = (
            "/orders", "/purchase-orders", "/appointments", "/commercial/quotes",
            "/commercial/projects", "/commercial/invoices",
        )
        is_history_resource = any(
            path.endswith(root) or re.search(re.escape(root) + r"/\d+$", path)
            for root in history_roots
        )
        is_payment_history = bool(
            re.search(r"/(?:orders|purchase-orders)/\d+/(?:payments|events)$", path)
        )
        is_inventory_history = path.endswith("/inventory/movements")
        history_read = method == "GET" and (is_history_resource or is_payment_history or is_inventory_history)
        if history_read:
            return
        parts = [part for part in path.split("/") if part]
        has_resource_id = any(part.isdigit() for part in parts)
        existing_edit = (
            has_resource_id
            and method in {"PATCH", "PUT"}
            and any(token in path for token in ("/orders/", "/appointments/"))
            and not any(token in path for token in ("/transition", "/payment-request", "/submit", "/checkout"))
        )
        safe_cancel = (
            has_resource_id and method == "POST"
            and any(token in path for token in ("/cancel", "/reject", "/discard"))
        )
        if existing_edit or safe_cancel:
            return
        raise HTTPException(
            status_code=403,
            detail={
                "code": "workspace_capability_disabled",
                "module": module,
                "required_capabilities": list(required),
                "message": "Công cụ này đang tắt trong Cài đặt của shop. Dữ liệu lịch sử vẫn được giữ.",
            },
        )

    return dependency
