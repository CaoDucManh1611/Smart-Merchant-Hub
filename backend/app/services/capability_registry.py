"""Tenant capability registry and fail-closed tool/workflow resolver.

This is an authorization contract for existing application services. It does
not create workflows, model calls, or a second persistence layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


CAPABILITY_REGISTRY_VERSION = "workspace_capabilities_v1"
CAPABILITY_IDS = (
    "CORE_CRM",
    "RETAIL_TOOLS",
    "APPOINTMENT_TOOLS",
    "PROJECT_QUOTATION_TOOLS",
    "INVENTORY_TOOLS",
    "ORDER_TOOLS",
    "CUSTOMER_TOOLS",
    "RENTAL_TOOLS",
    "PAYMENT_TOOLS",
    "RECOMMENDATION_TOOLS",
)

# Dependency names describe application integrations, not whether a shop has
# already entered catalog rows. Empty shop data remains a normal empty result.
SUPPORTED_DEPENDENCIES = frozenset({
    "tenant_crm", "conversation_service", "product_catalog", "pricing",
    "inventory_service", "order_workflow", "customer_records",
    "appointment_service_catalog", "booking_workflow", "schedule_service",
    "quotation_workflow", "project_management", "rental_offerings",
    "rental_availability", "rental_workflow",
    "payment_service", "recommendation_service", "personalization_consent",
})

CAPABILITY_REGISTRY: dict[str, dict[str, Any]] = {
    "CORE_CRM": {
        "name": "Lõi CRM", "dependencies": ["tenant_crm", "conversation_service"],
        "supported_workflows": ["conversation", "crm_profile", "human_handoff"],
        "available_tools": ["knowledge"],
    },
    "RETAIL_TOOLS": {
        "name": "Bán lẻ", "dependencies": ["product_catalog", "pricing"],
        "supported_workflows": ["product_inquiry", "product_management"],
        "available_tools": ["catalog"],
    },
    "APPOINTMENT_TOOLS": {
        "name": "Dịch vụ theo lịch", "dependencies": ["appointment_service_catalog", "booking_workflow", "schedule_service"],
        "supported_workflows": ["service_inquiry", "appointment_lookup", "appointment_booking"],
        "available_tools": ["catalog"],
    },
    "PROJECT_QUOTATION_TOOLS": {
        "name": "Báo giá & dự án", "dependencies": ["customer_records", "quotation_workflow", "project_management"],
        "supported_workflows": ["quotation", "project_management"],
        "available_tools": [],
    },
    "INVENTORY_TOOLS": {
        "name": "Kho & tồn", "dependencies": ["product_catalog", "inventory_service"],
        "supported_workflows": ["inventory_lookup", "inventory_adjustment"],
        "available_tools": ["catalog"],
    },
    "ORDER_TOOLS": {
        "name": "Đơn hàng", "dependencies": ["product_catalog", "order_workflow"],
        "supported_workflows": ["order_lookup", "order_collection"],
        "available_tools": ["orders"],
    },
    "CUSTOMER_TOOLS": {
        "name": "Thông tin khách hàng", "dependencies": ["customer_records"],
        "supported_workflows": ["customer_profile_lookup", "customer_follow_up"],
        "available_tools": ["customer"],
    },
    "RENTAL_TOOLS": {
        "name": "Cho thuê", "dependencies": ["rental_offerings", "rental_availability", "rental_workflow"],
        "supported_workflows": ["rental_inquiry", "rental_availability_lookup", "rental_request"],
        "available_tools": ["catalog"],
    },
    "PAYMENT_TOOLS": {
        "name": "Thanh toán", "dependencies": ["payment_configuration", "payment_service"],
        "supported_workflows": ["payment_instruction", "payment_status"],
        "available_tools": ["payment"],
    },
    "RECOMMENDATION_TOOLS": {
        "name": "Gợi ý sản phẩm", "dependencies": ["product_catalog", "recommendation_service", "personalization_consent"],
        "supported_workflows": ["product_recommendation"],
        "available_tools": ["recommendations"],
    },
}

# Capability prerequisites are explicit: enabling one never silently enables
# another. The resolver blocks the dependent operation until its prerequisite
# is enabled by the shop administrator.
CAPABILITY_PREREQUISITES = {
    "INVENTORY_TOOLS": ("RETAIL_TOOLS",),
    "ORDER_TOOLS": ("RETAIL_TOOLS",),
    "RECOMMENDATION_TOOLS": ("RETAIL_TOOLS",),
}

WORKFLOW_CAPABILITIES = {
    "human_handoff": "CORE_CRM",
    "product_inquiry": "RETAIL_TOOLS",
    "service_inquiry": "APPOINTMENT_TOOLS",
    "appointment_lookup": "APPOINTMENT_TOOLS",
    "appointment_booking": "APPOINTMENT_TOOLS",
    "quotation": "PROJECT_QUOTATION_TOOLS",
    "project_management": "PROJECT_QUOTATION_TOOLS",
    "inventory_lookup": "INVENTORY_TOOLS",
    "inventory_adjustment": "INVENTORY_TOOLS",
    "order_lookup": "ORDER_TOOLS",
    "order_collection": "ORDER_TOOLS",
    "customer_profile_lookup": "CUSTOMER_TOOLS",
    "customer_follow_up": "CUSTOMER_TOOLS",
    "rental_inquiry": "RENTAL_TOOLS",
    "rental_availability_lookup": "RENTAL_TOOLS",
    "rental_request": "RENTAL_TOOLS",
    "payment_instruction": "PAYMENT_TOOLS",
    "payment_status": "PAYMENT_TOOLS",
    "product_recommendation": "RECOMMENDATION_TOOLS",
}

DEFAULT_CAPABILITIES = ("CORE_CRM",)
BUSINESS_MODEL_TO_LEGACY = {
    "RETAIL": "retail",
    "APPOINTMENT_SERVICE": "services",
    "PROJECT_B2B": "b2b",
    "MULTI_SERVICE": "mixed",
}
LEGACY_TO_BUSINESS_MODEL = {value: key for key, value in BUSINESS_MODEL_TO_LEGACY.items()}
BUSINESS_MODEL_IDS = tuple(BUSINESS_MODEL_TO_LEGACY)

# Existing module toggles represented bundled permissions before granular
# capability settings existed. This compatibility mapping preserves that
# behavior until an administrator saves the new explicit list.
LEGACY_MODULE_CAPABILITIES = {
    "retail": (
        "RETAIL_TOOLS", "INVENTORY_TOOLS", "ORDER_TOOLS", "CUSTOMER_TOOLS",
        "PAYMENT_TOOLS", "RECOMMENDATION_TOOLS",
    ),
    "appointments": ("APPOINTMENT_TOOLS",),
    "projects": ("PROJECT_QUOTATION_TOOLS",),
}

TOOL_CAPABILITIES = {
    "knowledge": ("CORE_CRM",),
    "catalog": ("RETAIL_TOOLS",),
    "customer": ("CUSTOMER_TOOLS",),
    "orders": ("ORDER_TOOLS",),
    "payment": ("PAYMENT_TOOLS",),
    "recommendations": ("RECOMMENDATION_TOOLS", "RETAIL_TOOLS"),
}

# Direct chatbot tool execution is reachable both through the staff API and
# from internal services. Keep the mapping here so both boundaries enforce
# the same tenant capability contract.
CHATBOT_TOOL_CAPABILITY_REQUESTS: dict[str, dict[str, Any]] = {
    "tim_san_pham": {"tools": ("catalog",), "catalog_kind": "product"},
    "xem_ton_kho": {
        "tools": ("catalog",), "requested_workflow": "inventory_lookup", "catalog_kind": "product",
    },
    "tao_don_nhap": {"tools": ("orders",), "requested_workflow": "order_collection"},
    "xem_don_cua_khach": {"tools": ("orders",), "requested_workflow": "order_lookup"},
    "xem_trang_thai_don": {"tools": ("orders",), "requested_workflow": "order_lookup"},
    "yeu_cau_huy_don": {"tools": ("orders",), "requested_workflow": "order_collection"},
    "yeu_cau_hoan_don": {"tools": ("orders",), "requested_workflow": "order_collection"},
    "gan_tag": {"tools": ("customer",), "requested_workflow": "customer_profile_lookup"},
    "dat_lich_cham_soc": {"tools": ("customer",), "requested_workflow": "customer_follow_up"},
    "tao_ticket": {"tools": ("knowledge",), "requested_workflow": "human_handoff"},
    "chuyen_nhan_vien": {"tools": ("knowledge",), "requested_workflow": "human_handoff"},
    "dung_mau_tra_loi": {"tools": ("knowledge",)},
}


@dataclass(frozen=True)
class CapabilityResolution:
    allowed: bool
    requested_tools: tuple[str, ...]
    requested_workflow: str | None
    required_capabilities: tuple[str, ...]
    missing_capabilities: tuple[str, ...]
    missing_dependencies: tuple[str, ...]
    restrictions: tuple[str, ...]
    handoff_required: bool
    reason: str | None = None
    available_tools: tuple[str, ...] = ()
    allowed_workflows: tuple[str, ...] = ()
    required_dependencies: tuple[str, ...] = ()


def legacy_capabilities(enabled_modules: Iterable[str]) -> tuple[str, ...]:
    values = set(DEFAULT_CAPABILITIES)
    for module in enabled_modules:
        values.update(LEGACY_MODULE_CAPABILITIES.get(str(module), ()))
    return tuple(cap for cap in CAPABILITY_IDS if cap in values)


def enabled_capabilities(config: dict[str, Any] | None) -> tuple[str, ...]:
    """Read trusted normalized config; malformed configs retain CORE_CRM only."""
    if not isinstance(config, dict) or config.get("configuration_rejected"):
        return DEFAULT_CAPABILITIES
    values = config.get("enabled_capabilities")
    if not isinstance(values, (list, tuple, set)):
        return DEFAULT_CAPABILITIES
    normalized = {str(value) for value in values if str(value) in CAPABILITY_IDS}
    normalized.add("CORE_CRM")
    return tuple(cap for cap in CAPABILITY_IDS if cap in normalized)


def capability_details(
    config: dict[str, Any] | None,
    *,
    available_dependencies: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    active = set(enabled_capabilities(config))
    explicit = set((config or {}).get("explicitly_enabled_capabilities") or ())
    configured_dependencies = (config or {}).get("available_dependencies")
    available = set(
        available_dependencies
        if available_dependencies is not None
        else configured_dependencies
        if isinstance(configured_dependencies, (list, tuple, set, frozenset))
        else SUPPORTED_DEPENDENCIES
    )
    details = []
    for capability_id in CAPABILITY_IDS:
        definition = CAPABILITY_REGISTRY[capability_id]
        missing = [dependency for dependency in definition["dependencies"] if dependency not in available]
        missing_capabilities = [
            dependency for dependency in CAPABILITY_PREREQUISITES.get(capability_id, ())
            if dependency not in active
        ]
        enabled = capability_id in active
        dependency_status = (
            "disabled" if not enabled else
            "missing" if missing else
            "blocked" if missing_capabilities else
            "integration_available_shop_data_unchecked"
        )
        details.append({
            "capability_id": capability_id,
            "enabled": enabled,
            "explicitly_enabled": capability_id in explicit,
            "source": (config or {}).get("capability_source", "default"),
            "dependencies": list(definition["dependencies"]),
            "missing_dependencies": missing + [f"capability:{item}" for item in missing_capabilities],
            "missing_prerequisite_capabilities": missing_capabilities,
            "dependency_status": dependency_status,
            "tenant_data_status": "not_checked_until_tool_use",
            "supported_workflows": list(definition["supported_workflows"]),
            "available_tools": list(definition["available_tools"]),
            "configuration": {},
            "version": CAPABILITY_REGISTRY_VERSION,
        })
    return details


def resolve_capability_request(
    config: dict[str, Any] | None,
    *,
    tools: Iterable[str] = (),
    requested_workflow: str | None = None,
    conversation_state: dict[str, Any] | None = None,
    catalog_kind: str | None = None,
    available_dependencies: Iterable[str] | None = None,
) -> CapabilityResolution:
    """Authorize requested work from server-side tenant config, fail closed."""
    requested_tools = tuple(dict.fromkeys(str(tool) for tool in tools))
    context = planner_capability_context(config)

    def resolution(*args, required: Iterable[str] = (), **kwargs) -> CapabilityResolution:
        dependencies = {
            dependency
            for capability_id in required
            for dependency in CAPABILITY_REGISTRY.get(capability_id, {}).get("dependencies", ())
        }
        return CapabilityResolution(
            *args,
            **kwargs,
            available_tools=tuple(context["available_tools"]),
            allowed_workflows=tuple(context["available_workflows"]),
            required_dependencies=tuple(sorted(dependencies)),
        )

    if not isinstance(config, dict) or config.get("configuration_rejected"):
        # CORE_CRM, including customer support and human handoff, remains
        # available even when optional tenant settings are malformed.
        if requested_tools == ("knowledge",) and requested_workflow == "human_handoff":
            return resolution(True, requested_tools, requested_workflow, ("CORE_CRM",), (), (), (), False,
                              required=("CORE_CRM",))
        return resolution(False, requested_tools, requested_workflow, (), (), (),
                          ("tenant_configuration_unavailable",), True, "configuration_unavailable")
    active = set(enabled_capabilities(config))
    required: set[str] = set()
    unknown_tools = [tool for tool in requested_tools if tool not in TOOL_CAPABILITIES]
    if unknown_tools:
        return resolution(False, requested_tools, requested_workflow, (), (), (),
                          ("unknown_tool",), True, "unknown_tool")
    for tool in requested_tools:
        if tool == "catalog":
            if catalog_kind == "service":
                required.add("APPOINTMENT_TOOLS")
            elif catalog_kind == "rental":
                required.add("RENTAL_TOOLS")
            else:
                required.add("RETAIL_TOOLS")
        else:
            required.update(TOOL_CAPABILITIES[tool])
    if requested_workflow:
        workflow_capability = WORKFLOW_CAPABILITIES.get(requested_workflow)
        if workflow_capability is None:
            return resolution(False, requested_tools, requested_workflow, (), (), (),
                              ("unknown_workflow",), True, "unknown_workflow")
        required.add(workflow_capability)

    missing_capabilities = required - active
    missing_prerequisites = {
        prerequisite
        for capability_id in required & active
        for prerequisite in CAPABILITY_PREREQUISITES.get(capability_id, ())
        if prerequisite not in active
    }
    missing_capabilities.update(missing_prerequisites)

    configured_dependencies = (config or {}).get("available_dependencies") if isinstance(config, dict) else None
    available = set(
        available_dependencies
        if available_dependencies is not None
        else configured_dependencies
        if isinstance(configured_dependencies, (list, tuple, set, frozenset))
        else SUPPORTED_DEPENDENCIES
    )
    missing_dependencies = {
        dependency
        for capability_id in (required - (required & missing_capabilities))
        for dependency in CAPABILITY_REGISTRY[capability_id]["dependencies"]
        if dependency not in available
    }
    restrictions = []
    if missing_capabilities:
        restrictions.append("capability_disabled")
    if missing_dependencies:
        restrictions.append("dependency_unavailable")
    denied = bool(missing_capabilities or missing_dependencies)
    return resolution(
        allowed=not denied,
        requested_tools=requested_tools,
        requested_workflow=requested_workflow,
        required_capabilities=tuple(cap for cap in CAPABILITY_IDS if cap in required),
        missing_capabilities=tuple(cap for cap in CAPABILITY_IDS if cap in missing_capabilities),
        missing_dependencies=tuple(sorted(missing_dependencies)),
        restrictions=tuple(restrictions),
        handoff_required=denied,
        reason=("capability_disabled" if missing_capabilities else "dependency_unavailable" if missing_dependencies else None),
        required=required,
    )


def capability_for_workspace_module(module: str) -> tuple[str, ...]:
    """Capabilities represented by the legacy API module switch."""
    return tuple(LEGACY_MODULE_CAPABILITIES.get(module, ()))


def authorize_chatbot_tool(db: Any, business_id: int, tool_name: str) -> CapabilityResolution | None:
    """Resolve a chatbot tool against the current tenant config; failures deny.

    ``None`` means the tool has no explicit mapping and must be rejected by
    the caller. Importing the workspace reader lazily avoids a module cycle.
    """
    request = CHATBOT_TOOL_CAPABILITY_REQUESTS.get(str(tool_name))
    if request is None:
        return None
    try:
        from app.tenancy.workspace_modules import get_workspace_config

        config = get_workspace_config(db, business_id)
    except Exception:
        config = {"configuration_rejected": True, "enabled_capabilities": ["CORE_CRM"]}
    return resolve_capability_request(config, **request)


def capability_activation_issues(
    requested_capabilities: Iterable[str],
    *, available_dependencies: Iterable[str] | None = SUPPORTED_DEPENDENCIES,
) -> dict[str, list[str]]:
    """Describe why explicitly requested capabilities cannot be enabled yet."""
    requested = set(requested_capabilities) | {"CORE_CRM"}
    available = set(available_dependencies or ())
    issues: dict[str, list[str]] = {}
    for capability_id in CAPABILITY_IDS:
        if capability_id not in requested:
            continue
        definition = CAPABILITY_REGISTRY[capability_id]
        missing = [dependency for dependency in definition["dependencies"] if dependency not in available]
        missing.extend(
            f"capability:{required}"
            for required in CAPABILITY_PREREQUISITES.get(capability_id, ())
            if required not in requested
        )
        if missing:
            issues[capability_id] = missing
    return issues


def planner_capability_context(config: dict[str, Any] | None) -> dict[str, Any]:
    """Small, non-sensitive tenant capability snapshot for the existing planner."""
    if not isinstance(config, dict) or config.get("configuration_rejected"):
        return {
            "business_model": "RETAIL",
            "industry_ids": [],
            "enabled_capabilities": ["CORE_CRM"],
            "available_tools": ["knowledge"],
            "available_workflows": [],
            "configuration_rejected": True,
            "config_version": 1,
        }
    caps = set(enabled_capabilities(config))
    configured_dependencies = config.get("available_dependencies")
    available_dependencies = (
        configured_dependencies
        if isinstance(configured_dependencies, (list, tuple, set, frozenset))
        else SUPPORTED_DEPENDENCIES
    )
    return {
        "business_model": (config or {}).get("business_model", "RETAIL"),
        "industry_ids": list((config or {}).get("industry_ids") or []),
        "enabled_capabilities": [cap for cap in CAPABILITY_IDS if cap in caps],
        "available_tools": [
            tool for tool in TOOL_CAPABILITIES
            if (
                set(TOOL_CAPABILITIES[tool]).issubset(caps)
                or tool == "catalog" and bool(caps & {"RETAIL_TOOLS", "APPOINTMENT_TOOLS", "RENTAL_TOOLS"})
            )
            and not capability_activation_issues(set(TOOL_CAPABILITIES[tool]) | (
                {"RETAIL_TOOLS"} if tool == "catalog" and "RETAIL_TOOLS" in caps else set()
            ), available_dependencies=available_dependencies)
        ],
        "available_workflows": [
            workflow for workflow, capability in WORKFLOW_CAPABILITIES.items()
            if capability in caps and not capability_activation_issues(
                {capability}, available_dependencies=available_dependencies,
            )
        ],
        "configuration_rejected": bool((config or {}).get("configuration_rejected")),
        "config_version": int((config or {}).get("config_version", 1) or 1),
    }
