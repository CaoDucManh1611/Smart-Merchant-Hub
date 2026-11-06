from app.services.capability_registry import SUPPORTED_DEPENDENCIES
from app.services.sales_journey_contracts import JourneyStage, NextBestAction, ObjectionType
from app.services.sales_journey_engine import SalesJourneyEngine


FULL_CAPABILITIES = {
    "business_model": "RETAIL",
    "industry_ids": ["electronics"],
    "enabled_capabilities": ["CORE_CRM", "RETAIL_TOOLS", "RECOMMENDATION_TOOLS", "ORDER_TOOLS"],
    "available_dependencies": sorted(SUPPORTED_DEPENDENCIES),
}
ELECTRONICS = {"business_id": 1, "industry_ids": ["electronics"]}


def evaluate(
    engine,
    message,
    *,
    state=None,
    tenant="tenant-a",
    conversation="conversation-a",
    capability_config=FULL_CAPABILITIES,
    **kwargs,
):
    return engine.evaluate(
        tenant,
        conversation,
        message,
        state=state,
        industry_configuration=ELECTRONICS,
        capability_config=capability_config,
        **kwargs,
    )


def test_discovery_qualification_recommendation_comparison_and_objection_loop():
    engine = SalesJourneyEngine()
    first = evaluate(engine, "Tôi muốn mua laptop")
    assert first.state.stage is JourneyStage.DISCOVERY
    assert first.next_best_action is NextBestAction.DISCOVER_NEED
    assert first.state.missing_slots

    qualified = evaluate(
        engine,
        "Gợi ý laptop phù hợp, ngân sách 20 triệu, dùng để lập trình",
        state=first.state,
    )
    assert qualified.state.stage is JourneyStage.QUALIFICATION
    assert qualified.state.missing_slots == []

    recommended = evaluate(
        engine,
        "Gợi ý laptop phù hợp, ngân sách 20 triệu, dùng để lập trình",
        state=qualified.state,
    )
    assert recommended.state.stage is JourneyStage.RECOMMENDATION
    assert recommended.next_best_action is NextBestAction.RECOMMEND_OPTIONS

    compared = evaluate(engine, "So sánh hai mẫu này giúp mình", state=recommended.state)
    assert compared.state.stage is JourneyStage.COMPARISON
    assert compared.next_best_action is NextBestAction.COMPARE_OPTIONS

    objection = evaluate(engine, "Giá cao quá", state=recommended.state)
    assert objection.state.stage is JourneyStage.OBJECTION_HANDLING
    assert objection.state.objection_type is ObjectionType.PRICE_CONCERN
    assert objection.next_best_action is NextBestAction.ADDRESS_OBJECTION

    alternative = evaluate(engine, "Gợi ý loại rẻ hơn trong 20 triệu", state=objection.state)
    assert alternative.state.stage is JourneyStage.RECOMMENDATION


def test_closing_never_creates_transaction_and_requires_follow_up_or_proof():
    engine = SalesJourneyEngine()
    recommendation = evaluate(engine, "Gợi ý laptop phù hợp, ngân sách 20 triệu, dùng để lập trình")
    closing = evaluate(engine, "Mua luôn mẫu này", state=recommendation.state)
    assert closing.state.stage is JourneyStage.CLOSING
    assert closing.next_best_action is NextBestAction.OFFER_ORDER
    assert closing.transaction_created is False
    assert closing.side_effects == []

    follow_up = evaluate(engine, "Để tôi suy nghĩ thêm", state=closing.state)
    assert follow_up.state.stage is JourneyStage.FOLLOW_UP
    assert follow_up.next_best_action is NextBestAction.ANSWER_DIRECTLY

    after_sales_without_proof = evaluate(engine, "Cần hỗ trợ bảo hành", state=closing.state)
    assert after_sales_without_proof.state.stage is JourneyStage.HANDOFF
    assert "transaction_evidence" in after_sales_without_proof.state.handoff_reason

    after_sales = evaluate(
        engine,
        "Cần hỗ trợ bảo hành",
        state=closing.state,
        transaction_evidence={"order_id": "order-1"},
    )
    assert after_sales.state.stage is JourneyStage.AFTER_SALES
    assert after_sales.next_best_action is NextBestAction.AFTER_SALES_SUPPORT


def test_capability_disabled_is_fail_closed_and_does_not_request_disabled_tool():
    engine = SalesJourneyEngine()
    disabled = evaluate(
        engine,
        "Mua luôn laptop này",
        capability_config={"enabled_capabilities": ["CORE_CRM"]},
    )
    assert disabled.state.stage is JourneyStage.HANDOFF
    assert disabled.next_best_action is NextBestAction.OFFER_HUMAN_HANDOFF
    assert disabled.tool_plan.requested_tools == []
    assert disabled.tool_plan.handoff_required is True
    assert disabled.transaction_created is False


def test_price_first_turn_can_be_direct_catalog_plan_without_forcing_funnel():
    result = evaluate(SalesJourneyEngine(), "Giá laptop bao nhiêu?")
    assert result.state.stage is JourneyStage.DISCOVERY
    assert result.next_best_action is NextBestAction.SEARCH_CATALOG
    assert result.tool_plan.requested_tools == ["catalog"]
    assert result.llm_calls == result.network_calls == 0


def test_topic_and_product_change_reset_goal_slots_but_keep_scope():
    engine = SalesJourneyEngine()
    first = evaluate(engine, "Gợi ý laptop, ngân sách 20 triệu, dùng để lập trình")
    changed = evaluate(engine, "Đổi sản phẩm, tôi muốn tìm serum", state=first.state)
    assert changed.state.tenant_id == "tenant-a"
    assert changed.state.conversation_id == "conversation-a"
    assert changed.state.active_goal_id != first.state.active_goal_id
    assert "budget" not in changed.state.customer_constraints
    assert changed.state.collected_slots.get("product_or_service_interest") != first.state.collected_slots.get("product_or_service_interest")


def test_state_and_memory_are_isolated_by_tenant_and_conversation():
    engine = SalesJourneyEngine()
    original = evaluate(engine, "Gợi ý laptop, ngân sách 20 triệu, dùng để lập trình")
    cross_tenant = evaluate(engine, "Giá bao nhiêu?", state=original.state, tenant="tenant-b", conversation="conversation-a")
    assert cross_tenant.previous_stage is JourneyStage.UNKNOWN
    assert "state_missing_or_scope_mismatch_fallback" in cross_tenant.reason_codes
    cross_conversation = evaluate(engine, "Giá bao nhiêu?", state=original.state, tenant="tenant-a", conversation="conversation-b")
    assert cross_conversation.previous_stage is JourneyStage.UNKNOWN


def test_sensitive_healthcare_context_handoffs_without_diagnosis():
    engine = SalesJourneyEngine()
    result = engine.evaluate(
        "tenant-health",
        "c-health",
        "Tôi có triệu chứng nặng, cần chẩn đoán",
        industry_configuration={"industry_ids": ["healthcare_wellness"]},
        capability_config={"enabled_capabilities": ["CORE_CRM"]},
    )
    assert result.state.stage is JourneyStage.HANDOFF
    assert result.next_best_action is NextBestAction.OFFER_HUMAN_HANDOFF
    assert "sensitive_context_requires_human_review" in result.reason_codes


def test_stale_state_and_customer_mismatch_fall_back_without_reusing_slots():
    from datetime import datetime, timedelta, timezone

    stale = evaluate(
        SalesJourneyEngine(),
        "Gia bao nhieu?",
        state={
            "tenant_id": "tenant-a",
            "conversation_id": "conversation-a",
            "customer_id": "customer-a",
            "stage": "RECOMMENDATION",
            "collected_slots": {"budget": {"amount": 1, "currency": "VND", "operator": "lte"}},
            "updated_at": (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat(),
        },
        tenant="tenant-a",
        conversation="conversation-a",
    )
    assert stale.previous_stage is JourneyStage.UNKNOWN
    assert stale.state.collected_slots.get("budget") is None
    assert "state_missing_or_scope_mismatch_fallback" in stale.reason_codes

    customer_mismatch = evaluate(
        SalesJourneyEngine(),
        "Gia bao nhieu?",
        state={
            "tenant_id": "tenant-a",
            "conversation_id": "conversation-a",
            "customer_id": "customer-a",
            "stage": "RECOMMENDATION",
        },
        customer_id="customer-b",
    )
    assert customer_mismatch.previous_stage is JourneyStage.UNKNOWN


def test_needs_discovery_exposes_at_most_one_essential_question():
    result = evaluate(SalesJourneyEngine(), "Goi y laptop")
    assert result.needs["next_best_question"]
    assert len(result.needs["missing_slots"]) >= 1
    assert result.next_best_action is NextBestAction.DISCOVER_NEED


def test_unscoped_memory_is_ignored_fail_closed():
    result = evaluate(
        SalesJourneyEngine(),
        "Goi y laptop",
        memory={"constraints": {"budget": {"amount": 1, "currency": "VND", "operator": "lte"}}},
    )
    assert "memory_scope_mismatch_ignored" in result.reason_codes
    assert result.needs["budget"] is None
