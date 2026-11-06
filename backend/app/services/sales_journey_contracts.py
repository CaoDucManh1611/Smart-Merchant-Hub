"""Typed, persistence-neutral contracts for the Phase 2 sales journey.

The contracts deliberately describe planning state, not a second conversation
store.  The existing graph, memory service, catalog and capability registry
remain the authorities that an integration adapter can call later.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StringConstraints, field_validator


class JourneyStage(str, Enum):
    UNKNOWN = "UNKNOWN"
    DISCOVERY = "DISCOVERY"
    QUALIFICATION = "QUALIFICATION"
    RECOMMENDATION = "RECOMMENDATION"
    COMPARISON = "COMPARISON"
    OBJECTION_HANDLING = "OBJECTION_HANDLING"
    CLOSING = "CLOSING"
    FOLLOW_UP = "FOLLOW_UP"
    AFTER_SALES = "AFTER_SALES"
    HANDOFF = "HANDOFF"
    PAUSED = "PAUSED"


class NextBestAction(str, Enum):
    ANSWER_DIRECTLY = "ANSWER_DIRECTLY"
    ASK_CLARIFICATION = "ASK_CLARIFICATION"
    DISCOVER_NEED = "DISCOVER_NEED"
    QUALIFY_NEED = "QUALIFY_NEED"
    SEARCH_CATALOG = "SEARCH_CATALOG"
    RETRIEVE_KNOWLEDGE = "RETRIEVE_KNOWLEDGE"
    RECOMMEND_OPTIONS = "RECOMMEND_OPTIONS"
    COMPARE_OPTIONS = "COMPARE_OPTIONS"
    ADDRESS_OBJECTION = "ADDRESS_OBJECTION"
    OFFER_QUOTE = "OFFER_QUOTE"
    OFFER_BOOKING = "OFFER_BOOKING"
    OFFER_ORDER = "OFFER_ORDER"
    OFFER_HUMAN_HANDOFF = "OFFER_HUMAN_HANDOFF"
    FOLLOW_UP_IF_AUTHORIZED = "FOLLOW_UP_IF_AUTHORIZED"
    AFTER_SALES_SUPPORT = "AFTER_SALES_SUPPORT"


class ObjectionType(str, Enum):
    PRICE_CONCERN = "PRICE_CONCERN"
    QUALITY_CONCERN = "QUALITY_CONCERN"
    COMPATIBILITY_CONCERN = "COMPATIBILITY_CONCERN"
    TRUST_CONCERN = "TRUST_CONCERN"
    TIMING_CONCERN = "TIMING_CONCERN"
    DELIVERY_CONCERN = "DELIVERY_CONCERN"
    WARRANTY_CONCERN = "WARRANTY_CONCERN"
    NEED_MORE_INFORMATION = "NEED_MORE_INFORMATION"
    NOT_INTERESTED = "NOT_INTERESTED"
    OTHER = "OTHER"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, populate_by_name=True)


def _now() -> datetime:
    return datetime.now(timezone.utc)


JOURNEY_STATE_TTL = timedelta(minutes=30)
MAX_PERSISTED_JOURNEY_STATE_BYTES = 4096


class SalesJourneyState(StrictModel):
    """Current scoped journey state; it is safe to serialize and version."""

    tenant_id: str | int
    conversation_id: str | int
    customer_id: str | int | None = None
    active_goal_id: str | None = None
    stage: JourneyStage = JourneyStage.UNKNOWN
    stage_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    customer_intent: str = "unknown"
    purchase_readiness_signals: dict[str, Any] = Field(default_factory=dict)
    product_or_service_interest: str | None = None
    collected_slots: dict[str, Any] = Field(default_factory=dict)
    missing_slots: list[str] = Field(default_factory=list)
    customer_constraints: dict[str, Any] = Field(default_factory=dict)
    objection_type: ObjectionType | None = None
    selected_recommendations: list[str] = Field(default_factory=list)
    last_action: NextBestAction | None = None
    next_best_action: NextBestAction = NextBestAction.ANSWER_DIRECTLY
    handoff_reason: str | None = None
    state_version: int = Field(default=1, ge=1)
    updated_at: datetime = Field(default_factory=_now)

    @field_validator("tenant_id", "conversation_id")
    @classmethod
    def non_empty_scope(cls, value: str | int) -> str | int:
        if isinstance(value, str) and not value.strip():
            raise ValueError("scope identifiers cannot be empty")
        if isinstance(value, bool) or (isinstance(value, int) and value <= 0):
            raise ValueError("scope identifiers must be positive")
        return value

    def is_same_scope(
        self,
        tenant_id: str | int,
        conversation_id: str | int,
        customer_id: str | int | None = None,
    ) -> bool:
        return (
            self.tenant_id == tenant_id
            and self.conversation_id == conversation_id
            and self.customer_id == customer_id
        )

    def is_fresh(
        self,
        *,
        now: datetime | None = None,
        ttl: timedelta = JOURNEY_STATE_TTL,
    ) -> bool:
        """Return whether state is current enough to influence this turn."""
        stamp = self.updated_at
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        current = now or _now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        age = current - stamp
        return timedelta(0) <= age <= ttl


class ObjectionAssessment(StrictModel):
    category: ObjectionType
    evidence_required: list[str] = Field(default_factory=list)
    response_strategy: str
    follow_up_question: str | None = None
    handoff_condition: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class StageEvidence(StrictModel):
    """Deterministic observations used by the transition policy."""

    message: str = ""
    intent: str = "unknown"
    needs_complete: bool = False
    has_interest: bool = False
    comparison_requested: bool = False
    recommendation_requested: bool = False
    purchase_intent: bool = False
    transaction_completed: bool = False
    follow_up_requested: bool = False
    follow_up_authorized: bool = False
    stop_requested: bool = False
    human_requested: bool = False
    after_sales_requested: bool = False
    sensitive_context: bool = False
    topic_changed: bool = False
    product_changed: bool = False
    objection: ObjectionAssessment | None = None


class ToolPlan(StrictModel):
    """Capability-aware plan; it never executes a tool or workflow."""

    action: NextBestAction
    requested_tools: list[str] = Field(default_factory=list)
    requested_workflow: str | None = None
    evidence_required: list[str] = Field(default_factory=list)
    allowed: bool = True
    handoff_required: bool = False
    missing_capabilities: list[str] = Field(default_factory=list)
    missing_dependencies: list[str] = Field(default_factory=list)
    reason: str | None = None
    restrictions: list[str] = Field(default_factory=list)


class JourneyDecision(StrictModel):
    state: SalesJourneyState
    previous_stage: JourneyStage
    transition_reason: str
    next_best_action: NextBestAction
    tool_plan: ToolPlan
    needs: dict[str, Any] = Field(default_factory=dict)
    objection: ObjectionAssessment | None = None
    reason_codes: list[str] = Field(default_factory=list)
    response_guidance: list[str] = Field(default_factory=list)
    llm_calls: int = 0
    network_calls: int = 0
    side_effects: list[str] = Field(default_factory=list)
    transaction_created: bool = False


OpaqueGoalId = Annotated[
    str,
    StringConstraints(pattern=r"^goal:[0-9a-f]{16}$", min_length=21, max_length=21),
]
class JourneyPlanningFlags(StrictModel):
    """Small, non-verbatim planning signals allowed in durable state."""

    explicit_purchase_intent: StrictBool = False
    comparison_requested: StrictBool = False
    follow_up_requested: StrictBool = False


class PersistedJourneyState(StrictModel):
    """Data-minimized durable projection; runtime needs and free text stay transient."""

    tenant_id: Annotated[StrictInt, Field(gt=0, le=2_147_483_647)]
    conversation_id: Annotated[StrictInt, Field(gt=0, le=2_147_483_647)]
    customer_id: Annotated[StrictInt, Field(gt=0, le=2_147_483_647)] | None = None
    active_goal_id: OpaqueGoalId | None = None
    stage: JourneyStage = JourneyStage.UNKNOWN
    stage_confidence: Annotated[StrictFloat, Field(ge=0.0, le=1.0)] = 0.0
    next_best_action: NextBestAction = NextBestAction.ANSWER_DIRECTLY
    planning_flags: JourneyPlanningFlags = Field(default_factory=JourneyPlanningFlags)
    state_version: Annotated[StrictInt, Field(ge=1, le=2_147_483_647)] = 1
    updated_at: datetime = Field(default_factory=_now)


class SerializedJourneyState(StrictModel):
    """Versioned envelope for the bounded, privacy-safe projection only."""

    schema_name: Literal["sales_journey_state"] = Field(default="sales_journey_state", alias="schema")
    schema_version: Literal[2] = 2
    state: PersistedJourneyState


def state_from_mapping(value: SalesJourneyState | Mapping[str, Any]) -> SalesJourneyState:
    if isinstance(value, SalesJourneyState):
        return value
    return SalesJourneyState.model_validate(value)


__all__ = [
    "JourneyStage", "NextBestAction", "ObjectionType", "SalesJourneyState",
    "ObjectionAssessment", "StageEvidence", "ToolPlan", "JourneyDecision",
    "PersistedJourneyState", "JourneyPlanningFlags", "SerializedJourneyState",
    "JOURNEY_STATE_TTL", "MAX_PERSISTED_JOURNEY_STATE_BYTES", "state_from_mapping",
]
