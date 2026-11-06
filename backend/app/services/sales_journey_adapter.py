"""Integration seams for the existing brain, memory and capability services.

The adapters are intentionally dependency-injected.  No database, provider or
runtime graph is called from this Phase 2 package; an integration owner can
bind these seams after Agent 1's work is stable.
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from app.services.universal_sales_brain import (
    NeedsDiscovery,
    discover_needs,
    playbook_guidance,
    resolve_industry_profiles,
    sales_brain_context,
)

from .sales_journey_contracts import (
    JourneyPlanningFlags,
    MAX_PERSISTED_JOURNEY_STATE_BYTES,
    PersistedJourneyState,
    SalesJourneyState,
    SerializedJourneyState,
    state_from_mapping,
)


JOURNEY_STATE_METADATA_KEY = "sales_journey_state"


@dataclass(frozen=True)
class BrainResolution:
    needs: NeedsDiscovery
    context: dict[str, Any]
    guidance: dict[str, Any]


class NeedsDiscoveryAdapter(Protocol):
    def resolve(
        self,
        tenant_id: str | int,
        message: str,
        *,
        industry_configuration: Mapping[str, Any] | None = None,
        memory: Mapping[str, Any] | None = None,
    ) -> BrainResolution: ...


class UniversalSalesBrainAdapter:
    """Read-only adapter around Phase 1's deterministic Universal Sales Brain."""

    def resolve(
        self,
        tenant_id: str | int,
        message: str,
        *,
        industry_configuration: Mapping[str, Any] | None = None,
        memory: Mapping[str, Any] | None = None,
    ) -> BrainResolution:
        configured_business_id = (industry_configuration or {}).get("business_id")
        if configured_business_id is None and isinstance(tenant_id, int) and not isinstance(tenant_id, bool):
            configured_business_id = tenant_id
        if configured_business_id is None and industry_configuration is not None:
            # The Phase 1 contract uses an integer business_id.  An integration
            # may use an opaque tenant key, so use a local validation sentinel;
            # tenant isolation is still enforced by the Phase 2 state scope.
            configured_business_id = 1
            industry_configuration = {**dict(industry_configuration), "business_id": 1}
        try:
            business_id = int(configured_business_id)
        except (TypeError, ValueError):
            business_id = 0
        context = resolve_industry_profiles(business_id, industry_configuration)
        needs = discover_needs(message, context, memory=dict(memory or {}))
        return BrainResolution(
            needs=needs,
            context=sales_brain_context(context, needs),
            guidance=playbook_guidance(context, needs),
        )


class JourneyStateAdapter(Protocol):
    """Persistence-neutral interface; production bindings belong elsewhere."""

    def load(
        self,
        tenant_id: str | int,
        conversation_id: str | int,
        customer_id: str | int | None = None,
    ) -> SalesJourneyState | None: ...

    def save(self, state: SalesJourneyState) -> None: ...


class InMemoryJourneyStateAdapter:
    """Disposable test adapter, never used as application persistence."""

    def __init__(self) -> None:
        self._states: dict[tuple[str | int, str | int, str | int | None], SalesJourneyState] = {}

    @staticmethod
    def _key(tenant_id: str | int, conversation_id: str | int, customer_id: str | int | None) -> tuple[str | int, str | int, str | int | None]:
        return tenant_id, conversation_id, customer_id

    def load(self, tenant_id: str | int, conversation_id: str | int, customer_id: str | int | None = None) -> SalesJourneyState | None:
        value = self._states.get(self._key(tenant_id, conversation_id, customer_id))
        return value.model_copy(deep=True) if value is not None else None

    def save(self, state: SalesJourneyState) -> None:
        self._states[self._key(state.tenant_id, state.conversation_id, state.customer_id)] = state.model_copy(deep=True)

    def clear(self) -> None:
        self._states.clear()


def serialize_state(state: SalesJourneyState | Mapping[str, Any]) -> dict[str, Any]:
    """Project runtime state onto a bounded allowlist before durable storage."""
    runtime = state_from_mapping(state)
    signals = runtime.purchase_readiness_signals
    envelope = SerializedJourneyState(
        state=PersistedJourneyState(
            tenant_id=runtime.tenant_id,
            conversation_id=runtime.conversation_id,
            customer_id=runtime.customer_id,
            active_goal_id=runtime.active_goal_id,
            stage=runtime.stage,
            stage_confidence=runtime.stage_confidence,
            next_best_action=runtime.next_best_action,
            planning_flags=JourneyPlanningFlags(
                explicit_purchase_intent=signals.get("explicit_purchase_intent") is True,
                comparison_requested=signals.get("comparison_requested") is True,
                follow_up_requested=signals.get("follow_up_requested") is True,
            ),
            state_version=runtime.state_version,
            updated_at=runtime.updated_at,
        )
    )
    payload = envelope.model_dump(mode="json", by_alias=True)
    _validate_json_envelope_size(payload)
    return payload


def _validate_json_envelope_size(payload: Mapping[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_PERSISTED_JOURNEY_STATE_BYTES:
        raise ValueError("persisted journey envelope exceeds size limit")


def _validated_envelope(payload: Mapping[str, Any]) -> SerializedJourneyState:
    _validate_json_envelope_size(payload)
    return SerializedJourneyState.model_validate(payload)


def sanitize_journey_metadata(metadata: Mapping[str, Any] | None, *, allow_state: bool = False) -> dict[str, Any]:
    """Keep unrelated reply metadata and only a validated journey envelope."""
    if not isinstance(metadata, Mapping):
        return {}
    safe = {
        key: value
        for key, value in metadata.items()
        if not (isinstance(key, str) and key.startswith("sales_journey_"))
    }
    if allow_state:
        raw_state = metadata.get(JOURNEY_STATE_METADATA_KEY)
        if isinstance(raw_state, Mapping):
            try:
                safe[JOURNEY_STATE_METADATA_KEY] = _validated_envelope(raw_state).model_dump(
                    mode="json", by_alias=True
                )
            except Exception:
                pass
    return safe


def deserialize_state(
    payload: Mapping[str, Any] | None,
    *,
    tenant_id: str | int,
    conversation_id: str | int,
    customer_id: str | int | None = None,
    now=None,
) -> SalesJourneyState | None:
    """Fail closed for missing, corrupt, stale or cross-scope state."""
    if not isinstance(payload, Mapping):
        return None
    try:
        envelope = _validated_envelope(payload)
        persisted = envelope.state
    except Exception:
        return None
    if (
        persisted.tenant_id != tenant_id
        or persisted.conversation_id != conversation_id
        or persisted.customer_id != customer_id
    ):
        return None
    state = SalesJourneyState(
        tenant_id=persisted.tenant_id,
        conversation_id=persisted.conversation_id,
        customer_id=persisted.customer_id,
        active_goal_id=persisted.active_goal_id,
        stage=persisted.stage,
        stage_confidence=persisted.stage_confidence,
        purchase_readiness_signals=persisted.planning_flags.model_dump(),
        next_best_action=persisted.next_best_action,
        state_version=persisted.state_version,
        updated_at=persisted.updated_at,
    )
    if not state.is_fresh(now=now):
        return None
    return state


def clean_memory_context(memory: Mapping[str, Any] | None) -> dict[str, Any]:
    """Keep only the existing short-lived memory shape needed by discovery."""
    if not isinstance(memory, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in ("scope", "active_product_ids", "constraints", "pending_slot", "last_intent"):
        if key in memory:
            result[key] = deepcopy(memory[key])
    return result


__all__ = [
    "BrainResolution", "NeedsDiscoveryAdapter", "UniversalSalesBrainAdapter",
    "JourneyStateAdapter", "InMemoryJourneyStateAdapter", "serialize_state",
    "deserialize_state", "sanitize_journey_metadata", "clean_memory_context",
]
