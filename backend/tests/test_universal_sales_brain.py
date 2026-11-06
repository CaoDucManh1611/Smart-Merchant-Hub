from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.universal_sales_brain import (
    GENERIC_PLAYBOOK,
    IndustryResolver,
    VERTICAL_PLAYBOOKS,
    TenantIndustryConfig,
    discover_needs,
    resolve_industry_profiles,
)


def config(business_id, *industry_ids):
    return TenantIndustryConfig(business_id=business_id, industry_ids=industry_ids)


def test_phase_one_has_all_fourteen_data_driven_playbooks_and_generic_fallback():
    assert len(VERTICAL_PLAYBOOKS) == 14
    assert len({item.industry_id for item in VERTICAL_PLAYBOOKS.values()}) == 14
    fallback = resolve_industry_profiles(7)
    assert fallback.generic_fallback is True
    assert fallback.profiles[0].industry_id == GENERIC_PLAYBOOK.industry_id
    assert fallback.profiles[0].playbook_version == "universal-sales-v1"


def test_resolver_rejects_cross_tenant_and_unknown_industry_configuration():
    other_shop = resolve_industry_profiles(7, config(8, "automotive_motorbike"))
    unknown = resolve_industry_profiles(7, {"business_id": 7, "industry_ids": ["private_vertical"]})
    assert other_shop.generic_fallback and other_shop.configuration_rejected
    assert unknown.generic_fallback and unknown.configuration_rejected
    assert [profile.industry_id for profile in other_shop.profiles] == ["generic"]
    assert resolve_industry_profiles(0).business_id is None


def test_named_industry_resolver_uses_only_tenant_bound_configuration():
    resolver = IndustryResolver()
    trusted = resolver.resolve(7, config(7, "beauty_cosmetics"))
    mismatched = resolver.resolve(7, config(8, "beauty_cosmetics"))
    assert trusted.profiles[0].industry_id == "beauty_cosmetics"
    assert trusted.generic_fallback is False
    assert mismatched.generic_fallback is True
    assert mismatched.configuration_rejected is True


def test_multi_industry_shop_keeps_full_config_and_selects_only_applicable_playbook():
    context = resolve_industry_profiles(7, config(7, "electronics", "beauty_cosmetics"))
    needs = discover_needs("Tư vấn laptop cho mình", context)
    assert {profile.industry_id for profile in context.profiles} == {"electronics", "beauty_cosmetics"}
    assert needs.applicable_playbook_id == "electronics"
    assert needs.next_best_question == "Bạn dự kiến ngân sách khoảng bao nhiêu?"


def test_explicit_budget_and_purpose_are_not_asked_again():
    context = resolve_industry_profiles(7, config(7, "electronics"))
    needs = discover_needs("Tôi muốn mua laptop khoảng 15 triệu để học lập trình", context)
    assert needs.intent == "product_recommendation"
    assert needs.budget is not None and needs.budget.amount == 15_000_000
    assert needs.purpose == "hoc lap trinh"
    assert needs.required_slots == ("budget", "primary_use")
    assert needs.missing_slots == ()
    assert needs.next_best_question is None


def test_needs_discovery_asks_only_one_missing_essential_slot():
    context = resolve_industry_profiles(7, config(7, "electronics"))
    needs = discover_needs("Tư vấn laptop giúp mình", context)
    assert needs.missing_slots == ("budget", "primary_use")
    assert needs.next_best_question == "Bạn dự kiến ngân sách khoảng bao nhiêu?"


def test_generic_fallback_asks_for_interest_only_when_request_is_too_broad():
    context = resolve_industry_profiles(7)
    needs = discover_needs("Gợi ý giúp tôi", context)
    assert needs.product_service_interest is None
    assert needs.missing_slots == ("product_or_goal",)
    assert needs.next_best_question == "Bạn đang tìm sản phẩm/dịch vụ nào hoặc muốn giải quyết nhu cầu gì?"


def test_profile_slots_apply_to_advice_not_factual_price_lookup():
    context = resolve_industry_profiles(7, config(7, "beauty_cosmetics"))
    advice = discover_needs("Gợi ý serum giúp tôi", context)
    factual = discover_needs("Serum này giá bao nhiêu?", context)
    assert advice.next_best_question == "Bạn muốn cải thiện vấn đề da nào và da bạn thuộc loại nào?"
    assert factual.intent == "information"
    assert factual.next_best_question is None


def test_known_slot_is_not_reasked_and_new_topic_does_not_inherit_old_budget():
    context = resolve_industry_profiles(7, config(7, "electronics"))
    memory = {"constraints": {"budget": {"amount": 15_000_000, "currency": "VND", "operator": "lte"}}}
    followup = discover_needs("Loại rẻ hơn thì sao?", context, memory=memory)
    switched = discover_needs("Tư vấn laptop giúp mình", context, memory=memory)
    assert followup.budget is not None and followup.budget.amount == 15_000_000
    assert switched.budget is None
    assert switched.next_best_question == "Bạn dự kiến ngân sách khoảng bao nhiêu?"


def test_vehicle_compatibility_requires_vehicle_identity_until_customer_supplies_it():
    context = resolve_industry_profiles(7, config(7, "automotive_motorbike"))
    missing = discover_needs("Tư vấn phụ tùng phù hợp với xe tôi", context)
    known = discover_needs("Tư vấn phụ tùng phù hợp Wave Alpha 110", context)
    assert missing.next_best_question == "Bạn cho mình xin hãng, dòng xe và đời xe để đối chiếu đúng loại?"
    assert known.next_best_question is None
    assert known.constraints["vehicle"] == "wave alpha 110"


def test_profile_context_contains_no_catalog_facts_or_customer_data():
    from app.services.universal_sales_brain import playbook_guidance, sales_brain_context

    context = resolve_industry_profiles(7, config(7, "services_repair", "rental_business"))
    needs = discover_needs("Shop có dịch vụ sửa xe không?", context)
    guidance = playbook_guidance(context, needs)
    contract = sales_brain_context(context, needs)
    assert contract["business_id"] == 7
    assert set(contract["industry_ids"]) == {"services_repair", "rental_business"}
    assert guidance["active_playbook_id"] == "services_repair"
    assert "price" not in guidance and "stock" not in guidance
    assert guidance["prohibited_assumptions"]
    assert guidance["handoff_conditions"]


class _Query:
    def filter(self, *args): return self
    def order_by(self, *args): return self
    def limit(self, *args): return self
    def all(self): return []
    def first(self): return None


class _DB:
    def query(self, *args): return _Query()


def test_graph_uses_needs_discovery_without_an_extra_llm_call():
    from app.services.conversation_graph import graph_reply

    with patch("app.services.conversation_graph.call_llm") as model, \
         patch("app.rag.run_logger.RagRunLog"), \
         patch("app.services.quota_service.record_quota_usage"), \
         patch("app.services.auto_reply_service._hide_catalog_code_labels", side_effect=lambda answer, **_: answer), \
         patch("app.tenancy.workspace_modules.get_workspace_config", return_value={
             "business_id": 7,
             "business_model": "RETAIL",
             "industry_ids": ["electronics"],
             "enabled_capabilities": ["CORE_CRM", "RETAIL_TOOLS", "RECOMMENDATION_TOOLS"],
             "explicitly_enabled_capabilities": ["RETAIL_TOOLS", "RECOMMENDATION_TOOLS"],
             "config_version": 1,
         }):
        result = graph_reply(
            _DB(), business_id=7, conversation=SimpleNamespace(id=70, customer_id=700),
            query="Tư vấn laptop giúp mình", job_key="sales-brain-discovery",
            industry_config=config(7, "electronics"),
        )

    assert result.prompt == "Bạn dự kiến ngân sách khoảng bao nhiêu?"
    model.assert_not_called()


def test_existing_graph_planner_receives_scoped_playbook_context_in_its_same_call():
    from app.services.conversation_graph import plan_turn

    captured = []
    calls = []

    def model(messages):
        calls.append(1)
        captured.extend(messages)
        return '{"mode":"handoff","tools":[]}'

    plan_turn({"query":"Tư vấn laptop", "sales_brain_context":{"business_id":7,
        "industry_ids":["electronics"], "generic_fallback":False},
        "industry_playbook_guidance":{"active_playbook_id":"electronics"}}, model)
    background = captured[-1]["content"]
    assert '"business_id": 7' in background
    assert '"industry_ids": ["electronics"]' in background
    assert '"active_playbook_id": "electronics"' in background
    assert "trusted configured shop playbook handoff condition" in captured[0]["content"]
    assert len(captured) == 2
    assert len(calls) == 1


@pytest.mark.parametrize("amount,expected", [("500k", 500_000), ("dưới 200.000đ", 200_000), ("1,5 triệu", 1_500_000)])
def test_budget_parser_handles_common_vietnamese_currency_forms(amount, expected):
    context = resolve_industry_profiles(7, config(7, "electronics"))
    needs = discover_needs(f"Tư vấn laptop ngân sách {amount}", context)
    assert needs.budget is not None
    assert needs.budget.amount == expected
