from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.database.bases import TenantBase
from app.models.channel import Channel
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.message import Message
from app.services.sales_journey_adapter import BrainResolution, serialize_state
from app.services.sales_journey_contracts import (
    JourneyDecision,
    JourneyStage,
    NextBestAction,
    SalesJourneyState,
    ToolPlan,
)
from app.services.sales_journey_engine import SalesJourneyEngine
from app.services.sales_journey_graph_bridge import (
    JOURNEY_STATE_METADATA_KEY,
    build_graph_journey_bridge,
    graph_plan_for_decision,
    load_latest_journey_state,
)
from app.services.universal_sales_brain import Budget, NeedsDiscovery


class _FakeQuery:
    def __init__(self, row):
        self.row = row

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.row


class _FakeDb:
    def __init__(self, row):
        self.row = row

    def query(self, *args, **kwargs):
        return _FakeQuery(self.row)


class _FailingDb:
    def query(self, *args, **kwargs):
        raise RuntimeError("persistence unavailable")


def _decision(action, *, tools=(), workflow=None):
    state = SalesJourneyState(
        tenant_id=1,
        conversation_id=2,
        customer_id=3,
        stage=JourneyStage.DISCOVERY,
        next_best_action=action,
    )
    return JourneyDecision(
        state=state,
        previous_stage=JourneyStage.UNKNOWN,
        transition_reason="offline_test",
        next_best_action=action,
        tool_plan=ToolPlan(
            action=action,
            requested_tools=list(tools),
            requested_workflow=workflow,
        ),
    )


def _brain_resolution():
    return BrainResolution(
        needs=NeedsDiscovery(
            intent="information",
            product_service_interest="laptop",
            confidence=0.8,
        ),
        context={"needs": {"intent": "information"}},
        guidance={"active_playbook_id": "electronics"},
    )


def test_feature_flag_is_off_by_default():
    assert Settings.model_fields["SALES_JOURNEY_ENGINE_ENABLED"].default is False


@pytest.mark.parametrize(
    ("action", "tools", "workflow", "mode", "clarification"),
    [
        (NextBestAction.ASK_CLARIFICATION, (), None, "chat", True),
        (NextBestAction.DISCOVER_NEED, (), None, "chat", True),
        (NextBestAction.SEARCH_CATALOG, ("catalog",), None, "answer", False),
        (NextBestAction.RECOMMEND_OPTIONS, ("recommendations",), None, "answer", False),
        (NextBestAction.OFFER_BOOKING, (), "appointment_booking", "workflow", False),
        (NextBestAction.OFFER_ORDER, (), "order_collection", "workflow", False),
        (NextBestAction.OFFER_HUMAN_HANDOFF, (), None, "handoff", False),
        (NextBestAction.ANSWER_DIRECTLY, (), None, "chat", False),
    ],
)
def test_graph_plan_mapping_is_explicit(action, tools, workflow, mode, clarification):
    plan, selected_workflow, selected_clarification = graph_plan_for_decision(
        _decision(action, tools=tools, workflow=workflow)
    )
    assert plan["mode"] == mode
    assert selected_workflow == workflow
    assert selected_clarification is clarification
    assert len(plan.get("tools", [])) <= 3


def test_precomputed_brain_resolution_avoids_duplicate_needs_discovery():
    class NoCallAdapter:
        def resolve(self, *args, **kwargs):
            raise AssertionError("Needs Discovery must not be called twice")

    result = SalesJourneyEngine(brain_adapter=NoCallAdapter()).evaluate(
        1,
        2,
        "gia laptop bao nhieu",
        customer_id=3,
        industry_configuration={"business_id": 1, "industry_ids": ["electronics"]},
        capability_config={"enabled_capabilities": ["CORE_CRM", "RETAIL_TOOLS"]},
        brain_resolution=_brain_resolution(),
    )
    assert result.llm_calls == 0
    assert result.network_calls == 0


def test_state_round_trip_requires_exact_tenant_conversation_and_customer_scope():
    state = SalesJourneyState(tenant_id=1, conversation_id=2, customer_id=3)
    row = SimpleNamespace(metadata_={JOURNEY_STATE_METADATA_KEY: serialize_state(state)})
    assert load_latest_journey_state(
        _FakeDb(row), business_id=1, conversation_id=2, customer_id=3
    ).status == "loaded"

    wrong_scope = SalesJourneyState(tenant_id=1, conversation_id=2, customer_id=99)
    wrong_row = SimpleNamespace(metadata_={JOURNEY_STATE_METADATA_KEY: serialize_state(wrong_scope)})
    loaded = load_latest_journey_state(
        _FakeDb(wrong_row), business_id=1, conversation_id=2, customer_id=3
    )
    assert loaded.state is None
    assert loaded.status == "invalid_or_expired"


def test_stale_state_is_ignored_fail_closed():
    stale = SalesJourneyState(
        tenant_id=1,
        conversation_id=2,
        customer_id=3,
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=31),
    )
    row = SimpleNamespace(metadata_={JOURNEY_STATE_METADATA_KEY: serialize_state(stale)})
    loaded = load_latest_journey_state(
        _FakeDb(row), business_id=1, conversation_id=2, customer_id=3
    )
    assert loaded.state is None
    assert loaded.status == "invalid_or_expired"


def test_persistence_read_failure_keeps_bounded_write_and_no_transaction():
    result = build_graph_journey_bridge(
        _FailingDb(),
        business_id=1,
        conversation_id=2,
        customer_id=3,
        message="gia laptop bao nhieu",
        memory={},
        industry_configuration={"business_id": 1, "industry_ids": ["electronics"]},
        capability_config={"enabled_capabilities": ["CORE_CRM", "RETAIL_TOOLS"]},
        brain_resolution=_brain_resolution(),
        persistence_authorized=True,
    )
    assert result.state_load_status == "unavailable"
    assert JOURNEY_STATE_METADATA_KEY in result.metadata
    assert result.metadata[JOURNEY_STATE_METADATA_KEY]["schema_version"] == 2
    assert result.decision.transaction_created is False
    assert result.decision.side_effects == []


def test_unauthorized_persistence_does_not_read_or_emit_journey_state():
    class NoQueryDb:
        def query(self, *args, **kwargs):
            raise AssertionError("state reads require prior purpose/consent authorization")

    result = build_graph_journey_bridge(
        NoQueryDb(),
        business_id=1,
        conversation_id=2,
        customer_id=3,
        message="toi muon mua laptop",
        memory={},
        industry_configuration={"business_id": 1, "industry_ids": ["electronics"]},
        capability_config={"enabled_capabilities": ["CORE_CRM", "RETAIL_TOOLS"]},
        brain_resolution=_brain_resolution(),
    )
    assert result.state_load_status == "policy_or_consent_blocked"
    assert result.metadata == {}
    assert result.decision.llm_calls == 0
    assert result.decision.network_calls == 0


def test_two_turn_persistence_loads_only_sent_scoped_state():
    first = build_graph_journey_bridge(
        _FakeDb(None),
        business_id=1,
        conversation_id=2,
        customer_id=3,
        message="toi muon mua laptop",
        memory={},
        industry_configuration={"business_id": 1, "industry_ids": ["electronics"]},
        capability_config={
            "enabled_capabilities": ["CORE_CRM", "RETAIL_TOOLS", "RECOMMENDATION_TOOLS"],
        },
        brain_resolution=_brain_resolution(),
        persistence_authorized=True,
    )
    sent_row = SimpleNamespace(
        status="sent",
        metadata_={JOURNEY_STATE_METADATA_KEY: serialize_state(first.decision.state)},
    )
    second_brain = BrainResolution(
        needs=NeedsDiscovery(
            intent="recommendation",
            product_service_interest="laptop",
            budget=Budget(amount=20_000_000),
            purpose="lap trinh",
            confidence=0.9,
        ),
        context={"needs": {"intent": "recommendation"}},
        guidance={"active_playbook_id": "electronics"},
    )
    second = build_graph_journey_bridge(
        _FakeDb(sent_row),
        business_id=1,
        conversation_id=2,
        customer_id=3,
        message="ngan sach 20 trieu",
        memory={},
        industry_configuration={"business_id": 1, "industry_ids": ["electronics"]},
        capability_config={
            "enabled_capabilities": ["CORE_CRM", "RETAIL_TOOLS", "RECOMMENDATION_TOOLS"],
        },
        brain_resolution=second_brain,
        persistence_authorized=True,
    )
    assert first.state_load_status == "empty"
    assert second.state_load_status == "loaded"
    assert second.decision.previous_stage == first.decision.state.stage
    assert second.decision.state.state_version == first.decision.state.state_version + 1


def test_sqlite_round_trip_enforces_sent_scope_ttl_and_retry_boundaries():
    """Exercise the real loader query against a disposable SQLite schema."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    TenantBase.metadata.create_all(
        engine,
        tables=[Customer.__table__, Channel.__table__, Conversation.__table__, Message.__table__],
    )
    brain = _brain_resolution()

    with Session(engine) as db:
        customer = Customer(
            business_id=101,
            channel="test",
            external_user_id="synthetic-round-trip",
        )
        channel = Channel(
            business_id=101,
            channel_type="test",
            name="synthetic",
            external_account_id="synthetic-round-trip-account",
        )
        db.add_all([customer, channel])
        db.flush()
        conversation = Conversation(
            business_id=101,
            customer_id=customer.id,
            channel_id=channel.id,
            channel="test",
        )
        db.add(conversation)
        db.flush()

        first = build_graph_journey_bridge(
            db,
            business_id=101,
            conversation_id=conversation.id,
            customer_id=customer.id,
            message="toi muon mua laptop",
            memory={},
            industry_configuration={"business_id": 101, "industry_ids": ["electronics"]},
            capability_config={
                "enabled_capabilities": ["CORE_CRM", "RETAIL_TOOLS", "RECOMMENDATION_TOOLS"],
            },
            brain_resolution=brain,
            persistence_authorized=True,
        )
        assert first.state_load_status == "empty"
        assert first.decision.state.state_version == 1

        outbound = Message(
            sender_type="assistant",
            conversation_id=conversation.id,
            channel="test",
            direction="outbound",
            content="synthetic reply",
            status="sent",
            metadata_={JOURNEY_STATE_METADATA_KEY: first.metadata[JOURNEY_STATE_METADATA_KEY]},
        )
        db.add(outbound)
        db.commit()

        second = build_graph_journey_bridge(
            db,
            business_id=101,
            conversation_id=conversation.id,
            customer_id=customer.id,
            message="ngan sach 20 trieu",
            memory={},
            industry_configuration={"business_id": 101, "industry_ids": ["electronics"]},
            capability_config={
                "enabled_capabilities": ["CORE_CRM", "RETAIL_TOOLS", "RECOMMENDATION_TOOLS"],
            },
            brain_resolution=brain,
            persistence_authorized=True,
        )
        assert second.state_load_status == "loaded"
        assert second.decision.previous_stage == first.decision.state.stage
        assert second.decision.state.state_version == 2
        assert load_latest_journey_state(
            db,
            business_id=999,
            conversation_id=conversation.id,
            customer_id=customer.id,
        ).status == "empty"
        assert load_latest_journey_state(
            db,
            business_id=101,
            conversation_id=conversation.id,
            customer_id=999,
        ).status == "empty"

        outbound.status = "delivery_unknown"
        db.commit()
        assert load_latest_journey_state(
            db,
            business_id=101,
            conversation_id=conversation.id,
            customer_id=customer.id,
        ).status == "empty"

        outbound.status = "sent"
        outbound.metadata_ = {
            JOURNEY_STATE_METADATA_KEY: {
                "schema": "sales_journey_state",
                "schema_version": 999,
            }
        }
        db.commit()
        assert load_latest_journey_state(
            db,
            business_id=101,
            conversation_id=conversation.id,
            customer_id=customer.id,
        ).status == "invalid_or_expired"


def test_missing_or_unconfirmed_outbound_metadata_does_not_resume_state():
    row = SimpleNamespace(status="delivery_unknown", metadata_=None)
    loaded = load_latest_journey_state(
        _FakeDb(row), business_id=1, conversation_id=2, customer_id=3
    )
    assert loaded.state is None
    assert loaded.status == "invalid_or_expired"
    assert load_latest_journey_state(
        _FakeDb(None), business_id=1, conversation_id=2, customer_id=3
    ).status == "empty"


@pytest.mark.parametrize(
    ("message", "industry_ids", "capabilities", "expected_capability"),
    [
        ("gia laptop bao nhieu", ["electronics"], ["CORE_CRM"], "RETAIL_TOOLS"),
        ("mua luon laptop", ["electronics"], ["CORE_CRM", "RETAIL_TOOLS"], "ORDER_TOOLS"),
        ("dat lich sua xe", ["services_repair"], ["CORE_CRM"], "APPOINTMENT_TOOLS"),
    ],
)
def test_disabled_capabilities_handoff_without_transaction(
    message, industry_ids, capabilities, expected_capability
):
    result = SalesJourneyEngine().evaluate(
        1,
        2,
        message,
        customer_id=3,
        industry_configuration={"business_id": 1, "industry_ids": industry_ids},
        capability_config={"enabled_capabilities": capabilities},
    )
    assert result.next_best_action is NextBestAction.OFFER_HUMAN_HANDOFF
    assert expected_capability in result.tool_plan.missing_capabilities
    assert result.transaction_created is False
    assert result.side_effects == []


def test_booking_and_order_offers_are_not_success_claims_or_side_effects():
    booking = _decision(
        NextBestAction.OFFER_BOOKING,
        workflow="appointment_booking",
    )
    order = _decision(
        NextBestAction.OFFER_ORDER,
        workflow="order_collection",
    )
    for decision in (booking, order):
        plan, workflow, _ = graph_plan_for_decision(decision)
        assert plan["mode"] == "workflow"
        assert workflow in {"appointment_booking", "order_collection"}
        assert decision.transaction_created is False
        assert decision.side_effects == []


def test_handoff_mapping_does_not_claim_handoff_success():
    decision = _decision(NextBestAction.OFFER_HUMAN_HANDOFF)
    plan, workflow, clarification = graph_plan_for_decision(decision)
    assert plan == {"mode": "handoff", "tools": []}
    assert workflow is None
    assert clarification is False
    assert "ticket_id" not in _metadata_for_bridge_test(decision)


def _metadata_for_bridge_test(decision):
    result = build_graph_journey_bridge(
        _FakeDb(None),
        business_id=1,
        conversation_id=2,
        customer_id=3,
        message="can you help",
        memory={},
        industry_configuration={"business_id": 1, "industry_ids": ["electronics"]},
        capability_config={"enabled_capabilities": ["CORE_CRM"]},
        brain_resolution=_brain_resolution(),
        engine=_FixedDecisionEngine(decision),
    )
    return result.metadata


class _FixedDecisionEngine:
    def __init__(self, decision):
        self.decision = decision

    def evaluate(self, *args, **kwargs):
        return self.decision


def test_graph_source_keeps_flag_guard_authorization_and_answer_guard_order():
    source = Path(__file__).parents[1] / "app" / "services" / "conversation_graph.py"
    text = source.read_text(encoding="utf-8")
    flag = text.index("if settings.SALES_JOURNEY_ENGINE_ENABLED:")
    planner = text.index("graph=StateGraph(TurnState)")
    assert flag < planner
    assert "build_graph_journey_bridge" in text[flag:planner]
    authorization = text.index("persistence_authorization = authorize_journey_persistence", flag, planner)
    bridge_call = text.index("journey_bridge = build_graph_journey_bridge", flag, planner)
    assert authorization < bridge_call
    assert "persistence_authorized=persistence_authorization.allowed" in text[bridge_call:planner]
    assert "def authorize_plan(state):" in text
    assert "has_valid_citations" in text
    assert "sales_journey_metadata" in text[planner:]
