"""Deterministic transition and consultative-selling policy for Phase 2.

This module is intentionally free of provider calls and side effects.  It
classifies observable cues and produces a plan; the existing graph remains the
component that may later execute an approved plan.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping

from app.services.capability_registry import resolve_capability_request

from .sales_journey_contracts import (
    JourneyStage,
    NextBestAction,
    ObjectionAssessment,
    ObjectionType,
    SalesJourneyState,
    StageEvidence,
    ToolPlan,
)


def fold_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = text.replace("đ", "d").replace("ð", "d")
    return "".join(char for char in text if not unicodedata.combining(char))


def _contains(text: str, *cues: str) -> bool:
    return any(cue in text for cue in cues)


_HUMAN_CUES = (
    "gap nhan vien", "nhan vien", "tu van vien", "nguoi that", "human", "agent",
    "talk to someone", "call me", "goi cho toi", "chuyen nguoi",
)
_STOP_CUES = (
    "dung lai", "tam dung", "khong can nua", "khong quan tam", "thoi khoi",
    "bo qua", "stop", "pause", "not interested", "no thanks",
)
_COMPARE_CUES = ("so sanh", "khac nhau", "compare", "which one", "loai nao tot hon")
_RECOMMEND_CUES = (
    "goi y", "tu van", "nen chon", "phu hop", "recommend", "suggest",
    "nen mua", "mua loai nao", "tim giup", "lua chon", "re hon",
)
_PURCHASE_CUES = (
    "mua luon", "dat hang", "chot don", "tien hanh mua", "buy now", "order now",
    "toi lay", "cho minh dat", "dat ngay", "book now",
)
_FOLLOW_UP_CUES = (
    "de toi xem", "de minh xem", "suy nghi them", "goi lai sau", "lien he sau",
    "follow up", "think about it", "later", "chua quyet dinh",
)
_AFTER_SALES_CUES = (
    "bao hanh", "bao tri", "doi tra", "ho tro sau mua", "da mua roi", "don hang cua toi",
    "warranty", "return", "after sales", "my order",
)
_SENSITIVE_CUES = (
    "cap cuu", "trieu chung nang", "chan doan", "ke don", "thuoc dieu tri",
    "tu van phap ly", "hop dong phap ly", "dau tu", "cam ket loi nhuan",
)
_PRICE_CUES = ("dat qua", "mac qua", "gia cao", "khong du tien", "vuot ngan sach", "too expensive", "expensive", "over budget")
_QUALITY_CUES = ("chat luong", "ben khong", "co tot khong", "quality", "durable")
_COMPATIBILITY_CUES = ("tuong thich", "phu hop voi", "lap vua", "dung cho xe", "compatible", "fit")
_TRUST_CUES = ("uy tin", "chinh hang", "that khong", "tin cay", "trust", "authentic")
_TIMING_CUES = ("chua can", "de sau", "chua quyet", "thoi diem", "timing")
_DELIVERY_CUES = ("giao hang", "ship", "nhan hang", "delivery", "bao lau giao", "bao lau")
_WARRANTY_CUES = ("bao hanh", "doi tra", "warranty", "return")
_OTHER_OBJECTION_CUES = ("lo lang", "phan van", "khong chac", "concern", "not sure", "van de")
_INFO_CUES = ("gia", "gia bao nhieu", "bao nhieu tien", "thong tin", "la gi", "how much", "price")
_BOOKING_CUES = ("dat lich", "dat hen", "dat phong", "appointment", "booking", "book")
_QUOTE_CUES = ("bao gia", "quotation", "quote", "du toan", "de xuat")


@dataclass(frozen=True)
class TransitionResult:
    stage: JourneyStage
    reason: str
    confidence: float


def detect_objection(message: str) -> ObjectionAssessment | None:
    """Classify an objection without inventing a discount, policy or fact."""
    text = fold_text(message)
    if not text:
        return None
    if _contains(text, *_STOP_CUES):
        return ObjectionAssessment(
            category=ObjectionType.NOT_INTERESTED,
            response_strategy="acknowledge_and_stop_without_pressure",
            confidence=0.94,
        )
    checks = (
        (ObjectionType.PRICE_CONCERN, _PRICE_CUES,
         "check_budget_and_offer_evidence-backed_alternatives",
         "Ban muon giu muc ngan sach toi da khoang bao nhieu?",
         "price_or_discount_policy_is_not_available"),
        (ObjectionType.QUALITY_CONCERN, _QUALITY_CUES,
         "compare_verified_specs_reviews_or_warranty_only",
         "Ban dang uu tien do ben, thong so hay chinh sach bao hanh nao?",
         "quality_evidence_is_not_available"),
        (ObjectionType.COMPATIBILITY_CONCERN, _COMPATIBILITY_CUES,
         "collect_model_and_verify_fitment_before_claiming_compatibility",
         "Ban cho minh xin model, doi hoac thong so can doi chieu?",
         "compatibility_requires_verified_fitment_or_staff_check"),
        (ObjectionType.TRUST_CONCERN, _TRUST_CUES,
         "show_verified_source_policy_and_offer_human_review",
         "Ban muon minh kiem tra nguon thong tin hay chinh sach nao?",
         "trust_or_authenticity_requires_verified_business_evidence"),
        (ObjectionType.TIMING_CONCERN, _TIMING_CUES,
         "clarify_timeline_without_creating_false_urgency",
         "Ban muon xem lai vao thoi diem nao?",
         None),
        (ObjectionType.DELIVERY_CONCERN, _DELIVERY_CUES,
         "verify_current_delivery_scope_and_timing",
         "Ban can giao den khu vuc nao va khi nao?",
         "delivery_status_requires_current_workflow_evidence"),
        (ObjectionType.WARRANTY_CONCERN, _WARRANTY_CUES,
         "retrieve_verified_warranty_or_handoff_for_policy_review",
         "Ban dang quan tam thoi han hay dieu kien bao hanh nao?",
         "warranty_policy_requires_verified_source"),
        (ObjectionType.NEED_MORE_INFORMATION, ("chua hieu", "them thong tin", "more information", "need details"),
         "answer_only_from_verified_knowledge_and_ask_one_key_question",
         "Ban muon lam ro diem nao truoc?",
         None),
    )
    for category, cues, strategy, question, handoff in checks:
        if _contains(text, *cues):
            return ObjectionAssessment(
                category=category, response_strategy=strategy,
                follow_up_question=question, handoff_condition=handoff,
                evidence_required=["authoritative_business_source"], confidence=0.88,
            )
    if _contains(text, *_OTHER_OBJECTION_CUES):
        return ObjectionAssessment(
            category=ObjectionType.OTHER,
            response_strategy="clarify_the_specific_concern_before_recommending",
            follow_up_question="Ban dang phan van ve diem nao?",
            evidence_required=["customer_clarification"],
            confidence=0.68,
        )
    return None


def build_stage_evidence(
    message: str,
    *,
    intent: str = "unknown",
    needs_complete: bool = False,
    has_interest: bool = False,
    transaction_evidence: bool = False,
    follow_up_authorized: bool = False,
    topic_changed: bool = False,
    product_changed: bool = False,
) -> StageEvidence:
    text = fold_text(message)
    objection = detect_objection(message)
    return StageEvidence(
        message=message,
        intent=intent,
        needs_complete=needs_complete,
        has_interest=has_interest,
        comparison_requested=_contains(text, *_COMPARE_CUES),
        recommendation_requested=_contains(text, *_RECOMMEND_CUES)
        or intent in {"product_recommendation", "service_recommendation"},
        purchase_intent=_contains(text, *_PURCHASE_CUES) or intent in {"purchase", "booking"},
        transaction_completed=bool(transaction_evidence),
        follow_up_requested=_contains(text, *_FOLLOW_UP_CUES),
        follow_up_authorized=bool(follow_up_authorized),
        stop_requested=_contains(text, *_STOP_CUES),
        human_requested=_contains(text, *_HUMAN_CUES),
        after_sales_requested=_contains(text, *_AFTER_SALES_CUES),
        sensitive_context=_contains(text, *_SENSITIVE_CUES),
        topic_changed=topic_changed,
        product_changed=product_changed,
        objection=objection,
    )


def transition_with_reason(
    current_stage: JourneyStage | str,
    evidence: StageEvidence | Mapping[str, Any],
) -> TransitionResult:
    current = JourneyStage(current_stage)
    observation = evidence if isinstance(evidence, StageEvidence) else StageEvidence.model_validate(evidence)

    if observation.human_requested or observation.sensitive_context:
        reason = "human_requested" if observation.human_requested else "sensitive_context_requires_specialist"
        return TransitionResult(JourneyStage.HANDOFF, reason, 0.98)
    if observation.stop_requested:
        return TransitionResult(JourneyStage.PAUSED, "customer_requested_pause_or_declined", 0.98)
    if observation.after_sales_requested:
        if observation.transaction_completed:
            return TransitionResult(JourneyStage.AFTER_SALES, "verified_transaction_and_after_sales_request", 0.97)
        return TransitionResult(JourneyStage.HANDOFF, "after_sales_requires_transaction_evidence", 0.94)
    if observation.transaction_completed:
        return TransitionResult(JourneyStage.AFTER_SALES, "verified_transaction_completed", 0.99)

    if current == JourneyStage.PAUSED:
        if observation.has_interest or observation.recommendation_requested or observation.comparison_requested:
            return TransitionResult(JourneyStage.COMPARISON if observation.comparison_requested else JourneyStage.DISCOVERY,
                                    "customer_resumed_with_new_request", 0.86)
        return TransitionResult(JourneyStage.PAUSED, "pause_remains_active", 0.99)
    if current == JourneyStage.HANDOFF:
        return TransitionResult(JourneyStage.HANDOFF, "handoff_remains_active_until_resolved", 0.96)

    if observation.objection and observation.objection.category == ObjectionType.NOT_INTERESTED:
        return TransitionResult(JourneyStage.PAUSED, "customer_declined", 0.97)
    if observation.objection:
        if current == JourneyStage.OBJECTION_HANDLING and (
            observation.recommendation_requested or observation.has_interest and not observation.purchase_intent
        ):
            return TransitionResult(JourneyStage.RECOMMENDATION, "customer_requested_alternative_after_objection", 0.86)
        if observation.comparison_requested and current in {JourneyStage.RECOMMENDATION, JourneyStage.QUALIFICATION}:
            return TransitionResult(JourneyStage.OBJECTION_HANDLING, "objection_takes_priority_over_comparison", 0.91)
        if current != JourneyStage.OBJECTION_HANDLING:
            return TransitionResult(JourneyStage.OBJECTION_HANDLING, "customer_raised_objection", 0.92)
        return TransitionResult(JourneyStage.OBJECTION_HANDLING, "objection_still_unresolved", 0.93)

    if current == JourneyStage.OBJECTION_HANDLING and observation.recommendation_requested:
        return TransitionResult(JourneyStage.RECOMMENDATION, "customer_requested_alternative_after_objection", 0.86)

    if observation.comparison_requested:
        return TransitionResult(JourneyStage.COMPARISON, "customer_requested_comparison", 0.95)
    if current == JourneyStage.CLOSING:
        if observation.follow_up_requested or (observation.purchase_intent is False and observation.intent in {"unknown", "information"}):
            return TransitionResult(JourneyStage.FOLLOW_UP, "purchase_not_confirmed_and_follow_up_needed", 0.83)
        return TransitionResult(JourneyStage.CLOSING, "closing_signal_is_not_transaction_evidence", 0.91)
    if current == JourneyStage.FOLLOW_UP:
        if observation.follow_up_requested:
            return TransitionResult(JourneyStage.FOLLOW_UP, "follow_up_still_pending", 0.92)
        if observation.purchase_intent:
            return TransitionResult(JourneyStage.CLOSING, "customer_reopened_purchase_intent", 0.9)
        if observation.recommendation_requested or observation.has_interest:
            return TransitionResult(JourneyStage.RECOMMENDATION if observation.needs_complete else JourneyStage.DISCOVERY,
                                    "customer_reopened_sales_journey", 0.82)
    if current == JourneyStage.COMPARISON and observation.purchase_intent:
        return TransitionResult(JourneyStage.CLOSING, "clear_purchase_intent_after_comparison", 0.96)
    if current == JourneyStage.RECOMMENDATION and not observation.needs_complete and observation.has_interest:
        return TransitionResult(JourneyStage.QUALIFICATION, "recommendation_needs_one_more_qualification_slot", 0.84)
    if current == JourneyStage.QUALIFICATION and not observation.needs_complete:
        return TransitionResult(JourneyStage.DISCOVERY, "essential_need_information_is_missing", 0.9)
    if observation.purchase_intent:
        return TransitionResult(JourneyStage.CLOSING, "explicit_purchase_intent_without_completion_evidence", 0.95)

    if current == JourneyStage.UNKNOWN:
        if observation.intent in {"information", "price", "stock"}:
            return TransitionResult(JourneyStage.DISCOVERY, "direct_information_request_without_sales_funnel", 0.88)
        if observation.recommendation_requested:
            return TransitionResult(JourneyStage.QUALIFICATION if observation.needs_complete else JourneyStage.DISCOVERY,
                                    "initial_sales_intent_detected", 0.79)
        if observation.needs_complete and observation.has_interest:
            return TransitionResult(JourneyStage.QUALIFICATION, "initial_need_is_sufficient_for_qualification", 0.78)
        return TransitionResult(JourneyStage.DISCOVERY, "new_conversation_requires_discovery", 0.7)
    if current == JourneyStage.DISCOVERY and observation.needs_complete:
        return TransitionResult(JourneyStage.QUALIFICATION, "essential_needs_collected", 0.91)
    if current == JourneyStage.QUALIFICATION and observation.needs_complete and observation.recommendation_requested:
        return TransitionResult(JourneyStage.RECOMMENDATION, "qualified_need_ready_for_recommendation", 0.94)
    if current == JourneyStage.RECOMMENDATION and observation.recommendation_requested:
        return TransitionResult(JourneyStage.RECOMMENDATION, "recommendation_context_remains_active", 0.92)
    return TransitionResult(current, "stage_remains_until_stronger_signal", max(0.65, 0.75 if current != JourneyStage.UNKNOWN else 0.55))


def transition_stage(current_stage: JourneyStage | str, evidence: StageEvidence | Mapping[str, Any]) -> JourneyStage:
    """Convenience API returning only the deterministic next stage."""
    return transition_with_reason(current_stage, evidence).stage


def _business_model(capability_config: Mapping[str, Any] | None, industry_id: str | None) -> str:
    configured = str((capability_config or {}).get("business_model") or "").upper()
    if configured:
        return configured
    if industry_id in {"healthcare_wellness", "education", "travel_hospitality"}:
        return "APPOINTMENT_SERVICE"
    if industry_id in {"b2b_wholesale", "professional_services", "real_estate"}:
        return "PROJECT_B2B"
    if industry_id in {"services_repair", "rental_business"}:
        return "MULTI_SERVICE"
    return "RETAIL"


def _action_requirement(
    action: NextBestAction,
    *,
    industry_id: str | None,
    capability_config: Mapping[str, Any] | None,
    objection: ObjectionAssessment | None,
) -> tuple[tuple[str, ...], str | None, str | None, tuple[str, ...]]:
    model = _business_model(capability_config, industry_id)
    if action == NextBestAction.SEARCH_CATALOG:
        return ("catalog",), None, "goods", ("current_catalog_evidence",)
    if action == NextBestAction.RETRIEVE_KNOWLEDGE:
        return ("knowledge",), None, None, ("authoritative_knowledge_evidence",)
    if action == NextBestAction.RECOMMEND_OPTIONS:
        return ("recommendations",), "product_recommendation", "goods", ("catalog_and_recommendation_evidence",)
    if action == NextBestAction.COMPARE_OPTIONS:
        return ("catalog",), None, "goods", ("current_catalog_evidence", "comparison_basis")
    if action == NextBestAction.ADDRESS_OBJECTION:
        if objection and objection.category in {ObjectionType.TRUST_CONCERN, ObjectionType.WARRANTY_CONCERN, ObjectionType.NEED_MORE_INFORMATION}:
            return ("knowledge",), None, None, tuple(objection.evidence_required) or ("authoritative_knowledge_evidence",)
        return ("catalog",), None, "goods", tuple(objection.evidence_required) if objection else ("verified_business_evidence",)
    if action == NextBestAction.OFFER_BOOKING:
        return (), "appointment_booking", "service", ("booking_workflow_confirmation",)
    if action == NextBestAction.OFFER_QUOTE:
        return (), "quotation", None, ("quotation_workflow_confirmation",)
    if action == NextBestAction.OFFER_ORDER:
        return (), "order_collection", "goods", ("order_workflow_confirmation",)
    if action == NextBestAction.AFTER_SALES_SUPPORT:
        return ("knowledge",), None, None, ("verified_transaction_and_policy_evidence",)
    return (), None, None, ()


def make_tool_plan(
    action: NextBestAction,
    *,
    industry_id: str | None = None,
    capability_config: Mapping[str, Any] | None = None,
    objection: ObjectionAssessment | None = None,
) -> ToolPlan:
    """Authorize a plan with the existing fail-closed capability registry."""
    tools, workflow, catalog_kind, evidence = _action_requirement(
        action, industry_id=industry_id, capability_config=capability_config, objection=objection,
    )
    if not tools and not workflow:
        return ToolPlan(action=action, evidence_required=list(evidence))
    resolution = resolve_capability_request(
        dict(capability_config or {"enabled_capabilities": ["CORE_CRM"]}),
        tools=tools,
        requested_workflow=workflow,
        catalog_kind=catalog_kind,
    )
    return ToolPlan(
        action=action,
        requested_tools=list(resolution.requested_tools),
        requested_workflow=resolution.requested_workflow,
        evidence_required=list(evidence),
        allowed=resolution.allowed,
        handoff_required=resolution.handoff_required,
        missing_capabilities=list(resolution.missing_capabilities),
        missing_dependencies=list(resolution.missing_dependencies),
        reason=resolution.reason,
        restrictions=list(resolution.restrictions),
    )


def choose_action(
    stage: JourneyStage,
    evidence: StageEvidence,
    *,
    missing_slots: list[str] | tuple[str, ...] = (),
    intent: str = "unknown",
    industry_id: str | None = None,
    capability_config: Mapping[str, Any] | None = None,
    objection: ObjectionAssessment | None = None,
) -> tuple[NextBestAction, ToolPlan, list[str]]:
    if stage == JourneyStage.HANDOFF:
        return NextBestAction.OFFER_HUMAN_HANDOFF, make_tool_plan(NextBestAction.OFFER_HUMAN_HANDOFF), ["handoff_required"]
    if stage == JourneyStage.PAUSED:
        return NextBestAction.ANSWER_DIRECTLY, make_tool_plan(NextBestAction.ANSWER_DIRECTLY), ["respect_customer_pause"]
    if stage == JourneyStage.AFTER_SALES:
        action = NextBestAction.AFTER_SALES_SUPPORT
    elif stage == JourneyStage.OBJECTION_HANDLING:
        action = NextBestAction.ADDRESS_OBJECTION
    elif stage == JourneyStage.COMPARISON:
        action = NextBestAction.COMPARE_OPTIONS
    elif stage == JourneyStage.CLOSING:
        model = _business_model(capability_config, industry_id)
        if _contains(fold_text(evidence.message), *_BOOKING_CUES) or model == "APPOINTMENT_SERVICE":
            action = NextBestAction.OFFER_BOOKING
        elif _contains(fold_text(evidence.message), *_QUOTE_CUES) or model == "PROJECT_B2B":
            action = NextBestAction.OFFER_QUOTE
        else:
            action = NextBestAction.OFFER_ORDER
    elif stage == JourneyStage.FOLLOW_UP:
        action = NextBestAction.FOLLOW_UP_IF_AUTHORIZED if evidence.follow_up_authorized else NextBestAction.ANSWER_DIRECTLY
    elif stage == JourneyStage.RECOMMENDATION:
        action = NextBestAction.RECOMMEND_OPTIONS
    elif stage == JourneyStage.QUALIFICATION:
        action = NextBestAction.QUALIFY_NEED if missing_slots else NextBestAction.RECOMMEND_OPTIONS
    else:
        text = fold_text(evidence.message)
        if missing_slots:
            action = NextBestAction.DISCOVER_NEED
        elif intent in {"information", "price", "stock"} and evidence.has_interest:
            action = NextBestAction.SEARCH_CATALOG
        elif intent in {"information", "unknown"} and not evidence.has_interest:
            action = NextBestAction.RETRIEVE_KNOWLEDGE
        elif evidence.recommendation_requested:
            action = NextBestAction.RECOMMEND_OPTIONS
        elif _contains(text, *_INFO_CUES):
            action = NextBestAction.RETRIEVE_KNOWLEDGE
        else:
            action = NextBestAction.ASK_CLARIFICATION

    plan = make_tool_plan(action, industry_id=industry_id, capability_config=capability_config, objection=objection)
    reasons: list[str] = []
    if plan.handoff_required:
        reasons.append("requested_capability_unavailable")
        return NextBestAction.OFFER_HUMAN_HANDOFF, ToolPlan(
            action=NextBestAction.OFFER_HUMAN_HANDOFF,
            evidence_required=plan.evidence_required,
            allowed=True,
            handoff_required=True,
            missing_capabilities=plan.missing_capabilities,
            missing_dependencies=plan.missing_dependencies,
            reason=plan.reason or "capability_unavailable",
            restrictions=plan.restrictions,
        ), reasons
    if action in {NextBestAction.OFFER_ORDER, NextBestAction.OFFER_BOOKING, NextBestAction.OFFER_QUOTE}:
        reasons.append("offer_only_no_transaction_side_effect")
    if stage == JourneyStage.FOLLOW_UP and not evidence.follow_up_authorized:
        reasons.append("follow_up_requires_explicit_authorization")
    return action, plan, reasons


__all__ = [
    "TransitionResult", "fold_text", "detect_objection", "build_stage_evidence",
    "transition_with_reason", "transition_stage", "make_tool_plan", "choose_action",
]
