"""Small, fail-closed bridge from the offline journey engine to LangGraph.

The bridge maps plans and reads the latest server-written outbound message
metadata.  It does not execute tools, workflows, providers or transactions.
The existing turn service already carries ``CollectionFlowResult.metadata``
through the durable turn job and outbound Message metadata, so no migration is
needed for the versioned journey state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.models.conversation import Conversation
from app.models.message import Message

from .sales_journey_adapter import (
    JOURNEY_STATE_METADATA_KEY,
    BrainResolution,
    deserialize_state,
    serialize_state,
)
from .sales_journey_contracts import JourneyDecision, NextBestAction, SalesJourneyState
from .sales_journey_engine import SalesJourneyEngine


_CLARIFICATION_ACTIONS = {
    NextBestAction.ASK_CLARIFICATION,
    NextBestAction.DISCOVER_NEED,
    NextBestAction.QUALIFY_NEED,
}
_OFFER_ACTIONS = {
    NextBestAction.OFFER_BOOKING,
    NextBestAction.OFFER_QUOTE,
    NextBestAction.OFFER_ORDER,
}
_ANSWER_ACTIONS = {
    NextBestAction.RETRIEVE_KNOWLEDGE,
    NextBestAction.SEARCH_CATALOG,
    NextBestAction.RECOMMEND_OPTIONS,
    NextBestAction.COMPARE_OPTIONS,
    NextBestAction.ADDRESS_OBJECTION,
    NextBestAction.AFTER_SALES_SUPPORT,
}


@dataclass(frozen=True)
class JourneyStateLoad:
    state: SalesJourneyState | None
    status: str


@dataclass(frozen=True)
class GraphJourneyBridgeResult:
    decision: JourneyDecision
    graph_plan: dict[str, Any]
    workflow: str | None
    clarification: bool
    metadata: dict[str, Any]
    state_load_status: str


def graph_plan_for_decision(decision: JourneyDecision) -> tuple[dict[str, Any], str | None, bool]:
    """Map an NBA to the existing Graph plan shape, never to authorization."""
    action = decision.next_best_action
    requested_tools = list(decision.tool_plan.requested_tools)
    if action is NextBestAction.OFFER_HUMAN_HANDOFF:
        return {"mode": "handoff", "tools": []}, None, False
    if action in _OFFER_ACTIONS:
        return {"mode": "workflow", "tools": []}, decision.tool_plan.requested_workflow, False
    if action in _CLARIFICATION_ACTIONS:
        return {"mode": "chat", "tools": []}, None, True
    if action is NextBestAction.ANSWER_DIRECTLY:
        if requested_tools:
            return {"mode": "answer", "tools": requested_tools[:3]}, None, False
        return {"mode": "chat", "tools": []}, None, False
    if action in _ANSWER_ACTIONS:
        return {"mode": "answer", "tools": requested_tools[:3]}, None, False
    if action is NextBestAction.FOLLOW_UP_IF_AUTHORIZED:
        if requested_tools:
            return {"mode": "answer", "tools": requested_tools[:3]}, None, False
        return {"mode": "chat", "tools": []}, None, False
    return {"mode": "chat", "tools": []}, None, False


def _metadata_for_decision(decision: JourneyDecision) -> dict[str, Any]:
    """Return only a valid minimized envelope; serialization never blocks a reply."""
    try:
        return {JOURNEY_STATE_METADATA_KEY: serialize_state(decision.state)}
    except Exception:
        return {}


def load_latest_journey_state(
    db: Any,
    *,
    business_id: int,
    conversation_id: int,
    customer_id: int | None,
) -> JourneyStateLoad:
    """Load only the latest sent outbound state in the exact tenant scope."""
    try:
        message = (
            db.query(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .filter(
                Conversation.business_id == business_id,
                Conversation.id == conversation_id,
                Conversation.customer_id == customer_id,
                Message.direction == "outbound",
                Message.status == "sent",
            )
            .order_by(Message.id.desc())
            .first()
        )
    except Exception:  # persistence is optional; Graph must fail open to legacy planning
        return JourneyStateLoad(None, "unavailable")
    if message is None:
        return JourneyStateLoad(None, "empty")
    metadata = message.metadata_ if isinstance(message.metadata_, Mapping) else {}
    payload = metadata.get(JOURNEY_STATE_METADATA_KEY)
    state = deserialize_state(
        payload,
        tenant_id=business_id,
        conversation_id=conversation_id,
        customer_id=customer_id,
    )
    return JourneyStateLoad(state, "loaded" if state is not None else "invalid_or_expired")


def build_graph_journey_bridge(
    db: Any,
    *,
    business_id: int,
    conversation_id: int,
    customer_id: int | None,
    message: str,
    memory: Mapping[str, Any] | None,
    industry_configuration: Mapping[str, Any] | None,
    capability_config: Mapping[str, Any] | None,
    brain_resolution: BrainResolution,
    engine: SalesJourneyEngine | None = None,
    persistence_authorized: bool = False,
) -> GraphJourneyBridgeResult:
    loaded = (
        load_latest_journey_state(
            db,
            business_id=business_id,
            conversation_id=conversation_id,
            customer_id=customer_id,
        )
        if persistence_authorized
        else JourneyStateLoad(None, "policy_or_consent_blocked")
    )
    decision = (engine or SalesJourneyEngine()).evaluate(
        business_id,
        conversation_id,
        message,
        customer_id=customer_id,
        state=loaded.state,
        industry_configuration=industry_configuration,
        capability_config=capability_config,
        memory=memory,
        brain_resolution=brain_resolution,
    )
    plan, workflow, clarification = graph_plan_for_decision(decision)
    metadata = _metadata_for_decision(decision) if persistence_authorized else {}
    if persistence_authorized and not metadata:
        loaded = JourneyStateLoad(loaded.state, "state_rejected")
    return GraphJourneyBridgeResult(
        decision=decision,
        graph_plan=plan,
        workflow=workflow,
        clarification=clarification,
        metadata=metadata,
        state_load_status=loaded.status,
    )


__all__ = [
    "JOURNEY_STATE_METADATA_KEY",
    "JourneyStateLoad",
    "GraphJourneyBridgeResult",
    "graph_plan_for_decision",
    "load_latest_journey_state",
    "build_graph_journey_bridge",
]
