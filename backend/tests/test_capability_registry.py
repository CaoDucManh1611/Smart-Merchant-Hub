from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.chatbot import (
    _CHATBOT_TOOL_CAPABILITIES,
    create_followup,
    dispatch_followups,
    execute_tool,
    schedule_inactive_customers,
)
from app.services import chatbot_agent
from app.services.chatbot_agent import AGENT_TOOLS
from app.schemas.chatbot import ChatbotToolRequest, FollowUpCreate
from app.services.capability_registry import (
    CAPABILITY_IDS,
    CHATBOT_TOOL_CAPABILITY_REQUESTS,
    SUPPORTED_DEPENDENCIES,
    authorize_chatbot_tool,
    capability_activation_issues,
    capability_details,
    planner_capability_context,
    resolve_capability_request,
)


def test_registry_is_complete_and_core_is_the_only_implicit_grant():
    config = {"business_model": "RETAIL", "industry_ids": [], "enabled_capabilities": ["CORE_CRM"]}
    assert len(CAPABILITY_IDS) == 10
    assert planner_capability_context(config)["available_tools"] == ["knowledge"]
    details = capability_details(config)
    core = next(item for item in details if item["capability_id"] == "CORE_CRM")
    retail = next(item for item in details if item["capability_id"] == "RETAIL_TOOLS")
    assert core["enabled"] is True
    assert retail["enabled"] is False
    assert all("configuration" in item and "version" in item for item in details)


def test_shop_can_enable_multiple_independent_capabilities_and_industries():
    config = {
        "business_model": "MULTI_SERVICE",
        "industry_ids": ["beauty_cosmetics", "services_repair", "rental_business"],
        "enabled_capabilities": ["CORE_CRM", "APPOINTMENT_TOOLS", "PROJECT_QUOTATION_TOOLS", "RENTAL_TOOLS"],
    }
    resolution = resolve_capability_request(
        config, tools=("catalog",), requested_workflow="appointment_lookup", catalog_kind="service",
    )
    assert resolution.allowed is True
    context = planner_capability_context(config)
    assert context["business_model"] == "MULTI_SERVICE"
    assert context["industry_ids"] == config["industry_ids"]
    assert "appointment_lookup" in context["available_workflows"]
    assert "rental_request" in context["available_workflows"]
    assert "catalog" in context["available_tools"]


def test_resolver_denies_disabled_tool_and_unknown_workflow():
    config = {"enabled_capabilities": ["CORE_CRM"]}
    disabled = resolve_capability_request(config, tools=("catalog",))
    unknown = resolve_capability_request(config, requested_workflow="make_fake_transaction")
    assert disabled.allowed is False
    assert disabled.missing_capabilities == ("RETAIL_TOOLS",)
    assert disabled.reason == "capability_disabled"
    assert unknown.allowed is False
    assert unknown.reason == "unknown_workflow"


def test_resolver_reports_missing_integration_dependencies():
    config = {"enabled_capabilities": ["CORE_CRM", "RETAIL_TOOLS"]}
    resolution = resolve_capability_request(
        config, tools=("catalog",), available_dependencies={"tenant_crm", "conversation_service"},
    )
    assert resolution.allowed is False
    assert resolution.reason == "dependency_unavailable"
    assert set(resolution.missing_dependencies) == {"product_catalog", "pricing"}


def test_prerequisite_is_not_auto_enabled_and_activation_explains_why():
    issues = capability_activation_issues(["ORDER_TOOLS"])
    resolution = resolve_capability_request({"enabled_capabilities": ["CORE_CRM", "ORDER_TOOLS"]}, tools=("orders",))
    assert issues["ORDER_TOOLS"] == ["capability:RETAIL_TOOLS"]
    assert resolution.allowed is False
    assert resolution.missing_capabilities == ("RETAIL_TOOLS",)


def test_invalid_tenant_config_denies_optional_tools():
    resolution = resolve_capability_request(
        {"configuration_rejected": True, "enabled_capabilities": ["CORE_CRM", "RETAIL_TOOLS"]},
        tools=("catalog",),
    )
    assert resolution.allowed is False
    assert resolution.reason == "configuration_unavailable"


def test_invalid_tenant_config_keeps_core_human_handoff_available():
    resolution = resolve_capability_request(
        {"configuration_rejected": True},
        tools=("knowledge",),
        requested_workflow="human_handoff",
    )
    assert resolution.allowed is True
    assert resolution.required_capabilities == ("CORE_CRM",)

    unscoped_knowledge = resolve_capability_request(
        {"configuration_rejected": True},
        tools=("knowledge",),
    )
    assert unscoped_knowledge.allowed is False
    assert unscoped_knowledge.reason == "configuration_unavailable"

    optional = resolve_capability_request(
        {"configuration_rejected": True},
        tools=("catalog",),
        requested_workflow="product_lookup",
    )
    assert optional.allowed is False
    assert optional.reason == "configuration_unavailable"


def test_payment_tools_require_shop_specific_payment_configuration():
    assert "payment_configuration" not in SUPPORTED_DEPENDENCIES
    incomplete = {
        "enabled_capabilities": ["CORE_CRM", "PAYMENT_TOOLS"],
        "available_dependencies": sorted(SUPPORTED_DEPENDENCIES),
    }
    blocked = resolve_capability_request(incomplete, tools=("payment",))
    assert blocked.allowed is False
    assert blocked.reason == "dependency_unavailable"
    assert blocked.missing_dependencies == ("payment_configuration",)
    assert "payment" not in planner_capability_context(incomplete)["available_tools"]

    ready = {
        **incomplete,
        "available_dependencies": sorted(SUPPORTED_DEPENDENCIES | {"payment_configuration"}),
    }
    assert resolve_capability_request(ready, tools=("payment",)).allowed is True
    assert "payment" in planner_capability_context(ready)["available_tools"]


def test_direct_chatbot_catalog_and_transaction_tools_fail_closed_before_execution():
    config = {"enabled_capabilities": ["CORE_CRM"]}
    for tool in (
        "tim_san_pham", "xem_ton_kho", "tao_don_nhap", "xem_don_cua_khach",
        "dat_lich_cham_soc",
    ):
        with patch("app.api.chatbot.get_workspace_config", return_value=config), \
             patch("app.api.chatbot.execute_chatbot_tool") as execute:
            with pytest.raises(HTTPException) as error:
                execute_tool(
                    99,
                    ChatbotToolRequest(tool=tool),
                    db=object(),
                    platform_db=None,
                    tenant=SimpleNamespace(business_id=7),
                    actor=None,
                )
            assert error.value.status_code == 403
            assert error.value.detail["code"] == "workspace_capability_disabled"
            execute.assert_not_called()


def test_every_agent_tool_has_an_explicit_capability_mapping():
    assert set(AGENT_TOOLS) == set(_CHATBOT_TOOL_CAPABILITIES)
    assert set(AGENT_TOOLS) == set(CHATBOT_TOOL_CAPABILITY_REQUESTS)


def test_direct_chatbot_tool_without_mapping_fails_closed():
    with patch.dict("app.api.chatbot.AGENT_TOOLS", {"future_tool": "future"}), \
         patch("app.api.chatbot.get_workspace_config") as get_config, \
         patch("app.api.chatbot.execute_chatbot_tool") as execute:
        with pytest.raises(HTTPException) as error:
            execute_tool(
                99,
                ChatbotToolRequest(tool="future_tool"),
                db=object(),
                platform_db=None,
                tenant=SimpleNamespace(business_id=7),
                actor=None,
            )
    assert error.value.status_code == 403
    assert error.value.detail["code"] == "workspace_tool_unmapped"
    get_config.assert_not_called()
    execute.assert_not_called()


def test_direct_chatbot_tool_fails_closed_when_workspace_config_read_fails():
    with patch("app.api.chatbot.get_workspace_config", side_effect=RuntimeError("db unavailable")), \
         patch("app.api.chatbot.execute_chatbot_tool") as execute:
        with pytest.raises(HTTPException) as error:
            execute_tool(
                99,
                ChatbotToolRequest(tool="tim_san_pham"),
                db=object(),
                platform_db=None,
                tenant=SimpleNamespace(business_id=7),
                actor=None,
            )
    assert error.value.status_code == 403
    assert error.value.detail["code"] == "workspace_capability_disabled"
    execute.assert_not_called()


def test_direct_chatbot_catalog_tool_runs_only_when_required_capabilities_are_enabled():
    config = {
        "enabled_capabilities": ["CORE_CRM", "RETAIL_TOOLS", "INVENTORY_TOOLS"],
        "available_dependencies": sorted(SUPPORTED_DEPENDENCIES),
    }
    db = SimpleNamespace(commit=lambda: None)
    with patch("app.api.chatbot.get_workspace_config", return_value=config), \
         patch("app.api.chatbot.execute_chatbot_tool", return_value={"items": []}) as execute, \
         patch("app.api.chatbot.record_audit"):
        response = execute_tool(
            99,
            ChatbotToolRequest(tool="xem_ton_kho"),
            db=db,
            platform_db=None,
            tenant=SimpleNamespace(business_id=7),
            actor=None,
        )
    assert response == {"tool": "xem_ton_kho", "result": {"items": []}}
    execute.assert_called_once()


def test_execution_boundary_denies_disabled_capability_before_catalog_query():
    with patch("app.services.chatbot_agent._conversation"), \
         patch("app.tenancy.workspace_modules.get_workspace_config", return_value={
             "enabled_capabilities": ["CORE_CRM"],
         }), \
         patch("app.services.chatbot_agent._search_products") as search:
        with pytest.raises(ValueError, match="workspace_capability_disabled"):
            chatbot_agent.execute_chatbot_tool(
                object(), 7, 99, "tim_san_pham", {"query": "serum"},
            )
    search.assert_not_called()


@pytest.mark.parametrize("workspace_config", [
    {"enabled_capabilities": ["CORE_CRM"]},
    {"configuration_rejected": True},
])
def test_followup_write_endpoints_fail_closed_without_customer_tools(workspace_config):
    tenant = SimpleNamespace(business_id=7)
    db = object()
    with patch("app.services.chatbot_followup.get_workspace_config", return_value=workspace_config), \
         patch("app.api.chatbot.schedule_followup") as schedule, \
         patch("app.api.chatbot.dispatch_due_followups") as dispatch, \
         patch("app.api.chatbot.schedule_inactive_customer_followups") as schedule_inactive:
        routes = (
            lambda: create_followup(
                FollowUpCreate(
                    conversation_id=99,
                    message="Chào khách",
                    run_at="2026-11-06T09:00:00Z",
                ),
                db=db,
                tenant=tenant,
                actor=None,
            ),
            lambda: dispatch_followups(limit=10, db=db, tenant=tenant, actor=None),
            lambda: schedule_inactive_customers(
                inactive_days=30,
                run_in_minutes=5,
                limit=10,
                db=db,
                tenant=tenant,
                actor=None,
            ),
        )
        for route in routes:
            with pytest.raises(HTTPException) as error:
                route()
            assert error.value.status_code == 403
            assert error.value.detail["code"] == "workspace_capability_disabled"
            assert error.value.detail["required_capabilities"] == ["CUSTOMER_TOOLS"]
        schedule.assert_not_called()
        dispatch.assert_not_called()
        schedule_inactive.assert_not_called()


def test_customer_followup_capability_allows_write_endpoints_when_explicitly_enabled():
    config = {
        "enabled_capabilities": ["CORE_CRM", "CUSTOMER_TOOLS"],
        "available_dependencies": sorted(SUPPORTED_DEPENDENCIES),
    }
    with patch("app.services.chatbot_followup.get_workspace_config", return_value=config):
        from app.services.chatbot_followup import customer_followup_capability_enabled

        assert customer_followup_capability_enabled(object(), 7) is True


def test_execution_boundary_denies_when_workspace_config_cannot_be_read():
    with patch("app.services.chatbot_agent._conversation"), \
         patch("app.tenancy.workspace_modules.get_workspace_config", side_effect=RuntimeError("db unavailable")), \
         patch("app.services.chatbot_agent._search_products") as search:
        with pytest.raises(ValueError, match="workspace_capability_disabled"):
            chatbot_agent.execute_chatbot_tool(
                object(), 7, 99, "tim_san_pham", {"query": "serum"},
            )
    search.assert_not_called()


def test_execution_boundary_denies_registered_but_unmapped_future_tool():
    with patch.dict("app.services.chatbot_agent.AGENT_TOOLS", {"future_tool": "future"}), \
         patch("app.services.chatbot_agent._conversation"), \
         patch("app.tenancy.workspace_modules.get_workspace_config") as get_config:
        with pytest.raises(ValueError, match="workspace_tool_unmapped"):
            chatbot_agent.execute_chatbot_tool(object(), 7, 99, "future_tool", {})
    get_config.assert_not_called()


def test_service_capability_resolver_fails_closed_for_unknown_mapping():
    assert authorize_chatbot_tool(object(), 7, "not_registered") is None
