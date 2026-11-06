"""Offline Universal Sales Journey Engine.

The engine combines Phase 1's deterministic needs discovery with a small,
explicit state machine and the existing fail-closed capability registry.  It
returns a plan for the existing LangGraph; it does not invoke the graph,
providers, tools, workflows, persistence or transactions.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from app.services.universal_sales_brain import Budget

from .sales_journey_adapter import (
    BrainResolution,
    UniversalSalesBrainAdapter,
    clean_memory_context,
)
from .sales_journey_contracts import (
    JourneyDecision,
    JourneyStage,
    NextBestAction,
    SalesJourneyState,
    state_from_mapping,
)
from .sales_journey_policy import (
    build_stage_evidence,
    choose_action,
    fold_text,
    transition_with_reason,
)


_TOPIC_RESET_CUES = (
    "doi chu de", "doi san pham", "doi nganh", "chuyen chu de", "san pham khac", "nganh khac", "bat dau lai",
    "different product", "new topic", "start over", "switch industry",
)
_PRODUCT_SIGNAL_CUES = (
    "laptop", "dien thoai", "may tinh", "tivi", "tai nghe", "ao", "vay", "giay",
    "serum", "my pham", "xe", "lop", "nhot", "ban ghe", "sofa", "mon an", "ca phe",
    "nha", "can ho", "khoa hoc", "tour", "khach san", "dich vu", "sua chua", "thue",
    "bao hanh", "product", "service", "rental",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _bool_evidence(value: bool | Mapping[str, Any] | None) -> bool:
    if isinstance(value, bool):
        return value
    if not isinstance(value, Mapping):
        return False
    if value.get("transaction_completed") is True or value.get("completed") is True:
        return True
    return any(value.get(key) not in (None, "", False) for key in ("transaction_id", "order_id", "booking_id", "payment_id"))


def _scope_matches_memory(memory: Mapping[str, Any] | None, tenant_id: str | int, conversation_id: str | int, customer_id: str | int | None) -> bool:
    if not isinstance(memory, Mapping):
        return False
    scope = memory.get("scope")
    if not isinstance(scope, Mapping):
        return False
    tenant_value = scope.get("tenant_id", scope.get("business_id"))
    conversation_value = scope.get("conversation_id")
    customer_value = scope.get("customer_id")
    if tenant_value is None or conversation_value is None:
        return False
    if tenant_value != tenant_id:
        return False
    if conversation_value != conversation_id:
        return False
    if customer_id is not None and customer_value != customer_id:
        return False
    return True


def _goal_id(industry_id: str | None, intent: str, interest: str | None) -> str | None:
    if not interest and intent in {"unknown", "social"}:
        return None
    raw = f"{industry_id or 'generic'}|{intent}|{interest or 'unspecified'}"
    return "goal:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _has_interest(message: str, interest: str | None) -> bool:
    if interest:
        return True
    text = fold_text(message)
    return any(re.search(rf"\b{re.escape(cue.strip())}\b", text) for cue in _PRODUCT_SIGNAL_CUES)


def _collected_slots(needs: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if getattr(needs, "product_service_interest", None):
        result["product_or_service_interest"] = needs.product_service_interest
    if getattr(needs, "purpose", None):
        result["purpose"] = needs.purpose
    result.update(dict(getattr(needs, "preferences", {}) or {}))
    result.update(dict(getattr(needs, "constraints", {}) or {}))
    return result


class SalesJourneyEngine:
    """Pure orchestration of contracts, policy and existing read-only adapters."""

    def __init__(self, *, brain_adapter: UniversalSalesBrainAdapter | None = None) -> None:
        self.brain_adapter = brain_adapter or UniversalSalesBrainAdapter()

    def evaluate(
        self,
        tenant_id: str | int,
        conversation_id: str | int,
        message: str,
        *,
        customer_id: str | int | None = None,
        state: SalesJourneyState | Mapping[str, Any] | None = None,
        industry_configuration: Mapping[str, Any] | None = None,
        capability_config: Mapping[str, Any] | None = None,
        capability_configuration: Mapping[str, Any] | None = None,
        memory: Mapping[str, Any] | None = None,
        transaction_evidence: bool | Mapping[str, Any] | None = None,
        workflow_evidence: Mapping[str, Any] | None = None,
        follow_up_authorized: bool = False,
        selected_recommendations: list[str] | tuple[str, ...] | None = None,
        evidence: Mapping[str, Any] | None = None,
        brain_resolution: BrainResolution | None = None,
    ) -> JourneyDecision:
        """Evaluate one message without executing any external operation."""
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        if capability_config is None:
            capability_config = capability_configuration
        reason_codes: list[str] = []
        previous = self._safe_state(state, tenant_id, conversation_id, customer_id)
        if state is not None and previous is None:
            reason_codes.append("state_missing_or_scope_mismatch_fallback")
        previous_stage = previous.stage if previous is not None else JourneyStage.UNKNOWN
        prior_version = previous.state_version if previous is not None else 0
        prior_goal = previous.active_goal_id if previous is not None else None

        scoped_memory = clean_memory_context(memory) if _scope_matches_memory(memory, tenant_id, conversation_id, customer_id) else {}
        if memory is not None and not scoped_memory and not _scope_matches_memory(memory, tenant_id, conversation_id, customer_id):
            reason_codes.append("memory_scope_mismatch_ignored")

        explicit_evidence = dict(evidence or {})
        text = fold_text(message)
        topic_changed = bool(explicit_evidence.get("topic_changed")) or any(cue in text for cue in _TOPIC_RESET_CUES)
        product_changed = bool(explicit_evidence.get("product_changed")) or "doi san pham" in text or "san pham khac" in text or "different product" in text
        if previous is not None and not topic_changed and not product_changed:
            prior_constraints = dict(previous.customer_constraints)
            if prior_constraints:
                scoped_memory = {**scoped_memory, "constraints": {**prior_constraints, **dict(scoped_memory.get("constraints", {}))}}
        brain = brain_resolution or self.brain_adapter.resolve(
            tenant_id,
            message,
            industry_configuration=industry_configuration,
            memory=scoped_memory,
        )
        needs = brain.needs
        if previous is not None and not topic_changed and not product_changed:
            prior_slots = dict(previous.collected_slots)
            merged_constraints = {**dict(previous.customer_constraints), **dict(needs.constraints)}
            missing_slots = [slot for slot in needs.missing_slots if not self._slot_already_collected(slot, prior_slots, merged_constraints)]
            updates: dict[str, Any] = {
                "constraints": merged_constraints,
                "missing_slots": tuple(missing_slots),
                "product_service_interest": needs.product_service_interest or previous.product_or_service_interest,
            }
            if not missing_slots:
                updates["next_best_question"] = None
            if needs.budget is None and isinstance(merged_constraints.get("budget"), Mapping):
                try:
                    updates["budget"] = Budget.model_validate(merged_constraints["budget"])
                except Exception:
                    pass
            needs = needs.model_copy(update=updates)
        if needs.intent == "unknown" and _has_interest(message, needs.product_service_interest) and re.search(
            r"\b(?:gia|bao nhieu tien|how much|price)\b", text,
        ):
            # Preserve the existing brain while covering natural price-first
            # phrasing such as "gia laptop bao nhieu".
            needs = needs.model_copy(update={"intent": "information"})
        industry_id = brain.guidance.get("active_playbook_id")
        transaction_ok = _bool_evidence(transaction_evidence) or _bool_evidence(workflow_evidence)
        authorized_follow_up = bool(follow_up_authorized or explicit_evidence.get("follow_up_authorized"))
        stage_evidence = build_stage_evidence(
            message,
            intent=needs.intent,
            needs_complete=not bool(needs.missing_slots),
            has_interest=_has_interest(message, needs.product_service_interest),
            transaction_evidence=transaction_ok,
            follow_up_authorized=authorized_follow_up,
            topic_changed=topic_changed,
            product_changed=product_changed,
        )
        transition = transition_with_reason(previous_stage, stage_evidence)
        next_stage = transition.stage

        action, tool_plan, action_reasons = choose_action(
            next_stage,
            stage_evidence,
            missing_slots=list(needs.missing_slots),
            intent=needs.intent,
            industry_id=industry_id,
            capability_config=capability_config,
            objection=stage_evidence.objection,
        )
        reason_codes.extend(action_reasons)
        if stage_evidence.sensitive_context:
            reason_codes.append("sensitive_context_requires_human_review")

        handoff_reason = None
        if next_stage == JourneyStage.HANDOFF:
            handoff_reason = transition.reason
        if tool_plan.handoff_required:
            next_stage = JourneyStage.HANDOFF
            handoff_reason = tool_plan.reason or "requested_capability_unavailable"
            reason_codes.append("state_moved_to_handoff_for_capability_boundary")
            transition_reason = f"{transition.reason};{handoff_reason}"
        else:
            transition_reason = transition.reason

        active_goal = None if topic_changed else prior_goal
        if active_goal is None:
            active_goal = _goal_id(industry_id, needs.intent, needs.product_service_interest)
        collected = {} if topic_changed or product_changed else dict(previous.collected_slots) if previous else {}
        collected.update(_collected_slots(needs))
        recommendations = [] if topic_changed or product_changed else list(previous.selected_recommendations) if previous else []
        recommendations.extend(str(value) for value in (selected_recommendations or ()) if str(value) not in recommendations)

        state_out = SalesJourneyState(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            customer_id=customer_id if customer_id is not None else (previous.customer_id if previous else None),
            active_goal_id=active_goal,
            stage=next_stage,
            stage_confidence=transition.confidence,
            customer_intent=needs.intent,
            purchase_readiness_signals={
                "explicit_purchase_intent": stage_evidence.purchase_intent,
                "comparison_requested": stage_evidence.comparison_requested,
                "transaction_evidence": transaction_ok,
                "follow_up_requested": stage_evidence.follow_up_requested,
            },
            product_or_service_interest=needs.product_service_interest,
            collected_slots=collected,
            missing_slots=list(needs.missing_slots),
            customer_constraints=dict(needs.constraints),
            objection_type=stage_evidence.objection.category if stage_evidence.objection else None,
            selected_recommendations=recommendations,
            last_action=previous.next_best_action if previous else None,
            next_best_action=action,
            handoff_reason=handoff_reason,
            state_version=max(1, prior_version + 1),
            updated_at=_now(),
        )
        guidance = []
        guidance.extend(str(item) for item in brain.guidance.get("selection_criteria", ())[:3])
        guidance.extend(str(item) for item in brain.guidance.get("prohibited_assumptions", ())[:3])
        return JourneyDecision(
            state=state_out,
            previous_stage=previous_stage,
            transition_reason=transition_reason,
            next_best_action=action,
            tool_plan=tool_plan,
            needs=needs.model_dump(mode="json"),
            objection=stage_evidence.objection,
            reason_codes=reason_codes,
            response_guidance=guidance,
            llm_calls=0,
            network_calls=0,
            side_effects=[],
            transaction_created=False,
        )

    def step(self, *args: Any, **kwargs: Any) -> JourneyDecision:
        return self.evaluate(*args, **kwargs)

    def decide(self, *args: Any, **kwargs: Any) -> JourneyDecision:
        return self.evaluate(*args, **kwargs)

    @staticmethod
    def _safe_state(
        value: SalesJourneyState | Mapping[str, Any] | None,
        tenant_id: str | int,
        conversation_id: str | int,
        customer_id: str | int | None,
    ) -> SalesJourneyState | None:
        if value is None:
            return None
        try:
            state = state_from_mapping(value)
        except Exception:
            return None
        if not state.is_same_scope(tenant_id, conversation_id, customer_id):
            return None
        return state if state.is_fresh() else None

    @staticmethod
    def _slot_already_collected(slot: str, collected: Mapping[str, Any], constraints: Mapping[str, Any]) -> bool:
        if slot in collected or slot in constraints:
            return True
        aliases = {
            "primary_use": ("purpose", "product_or_service_interest"),
            "product_or_goal": ("product_or_service_interest", "purpose"),
            "desired_outcome": ("purpose",),
            "delivery_location": ("location",),
        }
        return any(alias in collected or alias in constraints for alias in aliases.get(slot, ()))


__all__ = ["SalesJourneyEngine"]
