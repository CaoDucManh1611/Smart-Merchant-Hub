import pytest

from app.services.sales_journey_contracts import JourneyStage, NextBestAction, ObjectionType
from app.services.sales_journey_policy import (
    build_stage_evidence,
    choose_action,
    detect_objection,
    make_tool_plan,
    transition_stage,
)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Máy này đắt quá", ObjectionType.PRICE_CONCERN),
        ("Chất lượng có tốt không?", ObjectionType.QUALITY_CONCERN),
        ("Có tương thích với xe của tôi không?", ObjectionType.COMPATIBILITY_CONCERN),
        ("Shop có uy tín không?", ObjectionType.TRUST_CONCERN),
        ("Bao lâu thì giao?", ObjectionType.DELIVERY_CONCERN),
        ("Bảo hành thế nào?", ObjectionType.WARRANTY_CONCERN),
        ("Tôi không quan tâm nữa", ObjectionType.NOT_INTERESTED),
    ],
)
def test_objection_foundation_is_category_and_evidence_oriented(message, expected):
    assessment = detect_objection(message)
    assert assessment is not None
    assert assessment.category is expected
    assert assessment.response_strategy
    assert assessment.follow_up_question or expected is ObjectionType.NOT_INTERESTED


def test_transition_examples_and_safety_boundaries():
    assert transition_stage(
        JourneyStage.DISCOVERY,
        {"needs_complete": True, "has_interest": True, "intent": "product_recommendation"},
    ) is JourneyStage.QUALIFICATION
    assert transition_stage(
        JourneyStage.QUALIFICATION,
        {"needs_complete": True, "recommendation_requested": True, "has_interest": True},
    ) is JourneyStage.RECOMMENDATION
    assert transition_stage(
        JourneyStage.RECOMMENDATION,
        {"comparison_requested": True},
    ) is JourneyStage.COMPARISON
    assert transition_stage(
        JourneyStage.COMPARISON,
        {"purchase_intent": True},
    ) is JourneyStage.CLOSING
    assert transition_stage(
        JourneyStage.CLOSING,
        {"follow_up_requested": True, "intent": "unknown"},
    ) is JourneyStage.FOLLOW_UP
    assert transition_stage(
        JourneyStage.CLOSING,
        {"after_sales_requested": True},
    ) is JourneyStage.HANDOFF
    assert transition_stage(
        JourneyStage.CLOSING,
        {"after_sales_requested": True, "transaction_completed": True},
    ) is JourneyStage.AFTER_SALES


def test_no_false_closing_from_weak_interest_signal():
    stage = transition_stage(JourneyStage.RECOMMENDATION, {"message": "Để tôi xem", "intent": "unknown"})
    assert stage is JourneyStage.RECOMMENDATION


def test_consultative_policy_uses_evidence_and_does_not_invent_discount():
    assessment = detect_objection("Giá cao quá")
    assert assessment is not None
    assert "discount" in assessment.response_strategy or "budget" in assessment.response_strategy
    assert "coupon" not in assessment.response_strategy
    assert "price_or_discount_policy_is_not_available" in (assessment.handoff_condition or "")


def test_follow_up_requires_authorization_and_tools_are_capability_aware():
    evidence = build_stage_evidence("Để tôi xem thêm", intent="unknown", follow_up_authorized=False)
    action, plan, reasons = choose_action(JourneyStage.FOLLOW_UP, evidence)
    assert action is NextBestAction.ANSWER_DIRECTLY
    assert "follow_up_requires_explicit_authorization" in reasons
    assert plan.requested_tools == []

    blocked = make_tool_plan(
        NextBestAction.OFFER_ORDER,
        industry_id="electronics",
        capability_config={"enabled_capabilities": ["CORE_CRM"]},
    )
    assert blocked.allowed is False
    assert blocked.handoff_required is True
    assert blocked.reason == "capability_disabled"


def test_missing_dependencies_are_fail_closed_with_evidence_boundary():
    blocked = make_tool_plan(
        NextBestAction.SEARCH_CATALOG,
        capability_config={
            "enabled_capabilities": ["CORE_CRM", "RETAIL_TOOLS"],
            "available_dependencies": ["tenant_crm", "conversation_service"],
        },
    )
    assert blocked.allowed is False
    assert blocked.handoff_required is True
    assert blocked.reason == "dependency_unavailable"
    assert {"product_catalog", "pricing"}.issubset(blocked.missing_dependencies)
    assert blocked.evidence_required == ["current_catalog_evidence"]


def test_invalid_transition_is_rejected_and_pause_is_sticky():
    with pytest.raises(ValueError):
        transition_stage("NOT_A_REAL_STAGE", {})
    assert transition_stage(JourneyStage.PAUSED, {"message": "xin chao"}) is JourneyStage.PAUSED
    assert transition_stage(
        JourneyStage.PAUSED,
        {"message": "toi muon xem san pham khac", "has_interest": True},
    ) is JourneyStage.DISCOVERY


def test_knowledge_and_catalog_plans_are_read_only_contracts():
    knowledge = make_tool_plan(NextBestAction.RETRIEVE_KNOWLEDGE, capability_config={"enabled_capabilities": ["CORE_CRM"]})
    assert knowledge.allowed is True
    assert knowledge.requested_tools == ["knowledge"]
    assert knowledge.evidence_required == ["authoritative_knowledge_evidence"]
    catalog = make_tool_plan(
        NextBestAction.SEARCH_CATALOG,
        capability_config={"enabled_capabilities": ["CORE_CRM", "RETAIL_TOOLS"]},
    )
    assert catalog.allowed is True
    assert catalog.requested_tools == ["catalog"]
