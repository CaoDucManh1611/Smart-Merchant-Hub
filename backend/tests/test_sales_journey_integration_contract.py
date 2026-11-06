from datetime import datetime, timedelta, timezone

from app.services.capability_registry import SUPPORTED_DEPENDENCIES
from app.services.sales_journey_adapter import (
    InMemoryJourneyStateAdapter,
    UniversalSalesBrainAdapter,
    clean_memory_context,
    deserialize_state,
    serialize_state,
)
from app.services.sales_journey_contracts import JourneyStage, NextBestAction, SalesJourneyState
from app.services.sales_journey_engine import SalesJourneyEngine


def test_state_serialization_round_trip_and_fail_closed_scope():
    state = SalesJourneyState(
        tenant_id=101,
        conversation_id=202,
        customer_id=303,
        stage=JourneyStage.RECOMMENDATION,
        next_best_action=NextBestAction.RECOMMEND_OPTIONS,
        collected_slots={"budget": {"amount": 20_000_000, "currency": "VND", "operator": "lte"}},
        customer_constraints={"customer_email": "not-for-persistence@example.test"},
    )
    payload = serialize_state(state)
    restored = deserialize_state(payload, tenant_id=101, conversation_id=202, customer_id=303)
    assert restored is not None
    assert restored.stage == state.stage
    assert restored.next_best_action == state.next_best_action
    assert restored.collected_slots == {}
    assert restored.customer_constraints == {}
    assert "not-for-persistence@example.test" not in str(payload)
    assert deserialize_state(payload, tenant_id=999, conversation_id=202, customer_id=303) is None
    assert deserialize_state({"schema": "sales_journey_state", "state": {}}, tenant_id=101, conversation_id=202) is None
    assert deserialize_state(None, tenant_id=101, conversation_id=202) is None


def test_state_version_customer_scope_and_staleness_fail_closed():
    now = datetime.now(timezone.utc)
    stale = SalesJourneyState(
        tenant_id=101,
        conversation_id=202,
        customer_id=303,
        updated_at=now - timedelta(minutes=31),
    )
    payload = serialize_state(stale)
    assert deserialize_state(
        payload,
        tenant_id=101,
        conversation_id=202,
        customer_id=303,
        now=now,
    ) is None

    fresh = serialize_state(SalesJourneyState(
        tenant_id=101,
        conversation_id=202,
        customer_id=303,
    ))
    assert deserialize_state(
        {**fresh, "schema_version": 2},
        tenant_id=101,
        conversation_id=202,
    ) is None
    assert deserialize_state(
        fresh,
        tenant_id=101,
        conversation_id=202,
        customer_id=304,
    ) is None
    unbound = serialize_state(SalesJourneyState(
        tenant_id=101,
        conversation_id=202,
    ))
    assert deserialize_state(
        unbound,
        tenant_id=101,
        conversation_id=202,
        customer_id=303,
    ) is None


def test_disposable_memory_adapter_is_scoped_and_does_not_persist_to_database():
    adapter = InMemoryJourneyStateAdapter()
    state = SalesJourneyState(tenant_id="tenant-a", conversation_id="conversation-a", customer_id="customer-a")
    adapter.save(state)
    assert adapter.load("tenant-a", "conversation-a", "customer-a") == state
    assert adapter.load("tenant-b", "conversation-a", "customer-a") is None
    assert adapter.load("tenant-a", "conversation-b", "customer-a") is None
    adapter.clear()
    assert adapter.load("tenant-a", "conversation-a", "customer-a") is None


def test_memory_context_keeps_existing_short_lived_shape_only():
    memory = {
        "scope": {"tenant_id": "tenant-a", "conversation_id": "conversation-a"},
        "active_product_ids": [1],
        "constraints": {"budget": {"amount": 500_000, "currency": "VND", "operator": "lte"}},
        "pending_slot": "budget",
        "last_intent": "price",
        "customer_email": "should-not-be-copied@example.test",
    }
    clean = clean_memory_context(memory)
    assert set(clean) == {"scope", "active_product_ids", "constraints", "pending_slot", "last_intent"}
    assert "customer_email" not in clean


def test_multi_industry_brain_and_service_shop_use_same_engine_contract():
    brain = UniversalSalesBrainAdapter()
    result = brain.resolve(
        "tenant-multi",
        "Tôi muốn mua serum cho da khô",
        industry_configuration={"industry_ids": ["beauty_cosmetics", "services_repair"]},
    )
    assert result.needs.applicable_playbook_id == "beauty_cosmetics"

    engine = SalesJourneyEngine()
    booking = engine.evaluate(
        "tenant-service",
        "conversation-service",
        "Đặt lịch sửa xe",
        industry_configuration={"industry_ids": ["services_repair"]},
        capability_config={
            "business_model": "MULTI_SERVICE",
            "industry_ids": ["services_repair"],
            "enabled_capabilities": ["CORE_CRM", "APPOINTMENT_TOOLS"],
            "available_dependencies": sorted(SUPPORTED_DEPENDENCIES),
        },
    )
    assert booking.state.stage is JourneyStage.CLOSING
    assert booking.next_best_action is NextBestAction.OFFER_BOOKING
    assert booking.transaction_created is False


def test_missing_or_corrupt_state_falls_back_without_provider_calls():
    engine = SalesJourneyEngine()
    result = engine.evaluate(
        "tenant-a",
        "conversation-a",
        "Xin chào",
        state={"stage": "not-a-stage"},
    )
    assert result.previous_stage is JourneyStage.UNKNOWN
    assert "state_missing_or_scope_mismatch_fallback" in result.reason_codes
    assert result.llm_calls == 0
    assert result.network_calls == 0
    assert result.side_effects == []
