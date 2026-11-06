from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from unittest.mock import Mock

from app.core.config import settings
from app.database.bases import TenantBase
from app.models.channel import Channel
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.customer_collection import CustomerConsent
from app.models.message import Message
from app.services.sales_journey_adapter import (
    JOURNEY_STATE_METADATA_KEY,
    sanitize_journey_metadata,
    serialize_state,
    deserialize_state,
)
from app.services.sales_journey_contracts import (
    JourneyStage,
    NextBestAction,
    PersistedJourneyState,
    SalesJourneyState,
)
from app.services.sales_journey_privacy import (
    authorize_journey_persistence,
    filter_journey_metadata_for_persistence,
)


@pytest.fixture
def consent_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    tables = [
        Customer.__table__,
        Channel.__table__,
        Conversation.__table__,
        Message.__table__,
        CustomerConsent.__table__,
    ]
    TenantBase.metadata.create_all(engine, tables=tables)
    with Session(engine) as db:
        customer = Customer(
            business_id=101,
            channel="test",
            external_user_id="synthetic-privacy-test",
        )
        channel = Channel(
            business_id=101,
            channel_type="test",
            name="synthetic",
            external_account_id="synthetic-privacy-test",
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
        yield db, customer.id, conversation.id
    engine.dispose()


def _runtime_state(*, tenant_id=101, conversation_id=202, customer_id=303, **updates):
    values = {
        "tenant_id": tenant_id,
        "conversation_id": conversation_id,
        "customer_id": customer_id,
        "stage": JourneyStage.QUALIFICATION,
        "stage_confidence": 0.75,
        "active_goal_id": "goal:0123456789abcdef",
        "next_best_action": NextBestAction.ASK_CLARIFICATION,
        "purchase_readiness_signals": {
            "explicit_purchase_intent": True,
            "comparison_requested": False,
            "follow_up_requested": True,
            "unapproved_raw_signal": "private customer text",
        },
        "collected_slots": {
            "email": "customer@example.test",
            "address": {"line1": "private address"},
        },
        "customer_constraints": {"budget": {"amount": 500000}},
        "updated_at": datetime.now(timezone.utc),
    }
    values.update(updates)
    return SalesJourneyState(**values)


def _valid_settings(monkeypatch):
    monkeypatch.setattr(settings, "SALES_JOURNEY_PERSISTENCE_PURPOSE", "sales_journey_context")
    monkeypatch.setattr(settings, "SALES_JOURNEY_PERSISTENCE_POLICY_VERSION", "v1")
    monkeypatch.setattr(settings, "SALES_JOURNEY_PERSISTENCE_REQUIRES_CONSENT", True)


def _add_consent(db, customer_id, *, status="granted", purpose="sales_journey_context", version="v1", revoked_at=None):
    consent = CustomerConsent(
        business_id=101,
        customer_id=customer_id,
        purpose=purpose,
        status=status,
        policy_version=version,
        granted_at=datetime.now(timezone.utc) if status == "granted" else None,
        revoked_at=revoked_at,
    )
    db.add(consent)
    db.flush()
    return consent


def test_persisted_state_is_an_allowlisted_projection_and_round_trips_exact_scope():
    state = _runtime_state()
    payload = serialize_state(state)

    assert payload["schema"] == "sales_journey_state"
    assert payload["schema_version"] == 2
    assert set(payload["state"]) == {
        "tenant_id", "conversation_id", "customer_id", "active_goal_id", "stage",
        "stage_confidence", "next_best_action", "planning_flags", "state_version", "updated_at",
    }
    assert payload["state"]["planning_flags"] == {
        "explicit_purchase_intent": True,
        "comparison_requested": False,
        "follow_up_requested": True,
    }
    assert "customer@example.test" not in str(payload)
    assert "private address" not in str(payload)
    assert "private customer text" not in str(payload)

    restored = deserialize_state(payload, tenant_id=101, conversation_id=202, customer_id=303)
    assert restored is not None
    assert restored.stage is JourneyStage.QUALIFICATION
    assert restored.next_best_action is NextBestAction.ASK_CLARIFICATION
    assert restored.collected_slots == {}
    assert restored.customer_constraints == {}
    assert restored.purchase_readiness_signals == payload["state"]["planning_flags"]
    assert deserialize_state(payload, tenant_id=101, conversation_id=999, customer_id=303) is None
    assert deserialize_state(payload, tenant_id=101, conversation_id=202, customer_id=999) is None
    assert deserialize_state(payload, tenant_id=999, conversation_id=202, customer_id=303) is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["state"].update({"raw_message": "private customer text"}),
        lambda payload: payload["state"].update({"email": "customer@example.test"}),
        lambda payload: payload["state"].update({"nested": {"phone": "0000000000"}}),
        lambda payload: payload.update({"schema_version": 1}),
        lambda payload: payload["state"].update({"planning_flags": {"explicit_purchase_intent": 1}}),
    ],
)
def test_unknown_legacy_and_wrongly_typed_persisted_fields_are_rejected(mutation):
    payload = serialize_state(_runtime_state())
    mutation(payload)
    assert deserialize_state(payload, tenant_id=101, conversation_id=202, customer_id=303) is None
    assert sanitize_journey_metadata({JOURNEY_STATE_METADATA_KEY: payload}, allow_state=True) == {}


def test_oversized_goal_and_json_envelope_are_rejected():
    with pytest.raises(ValidationError):
        serialize_state(_runtime_state(active_goal_id="x" * 5000))

    with pytest.raises(ValidationError):
        PersistedJourneyState.model_validate({
            "tenant_id": 101,
            "conversation_id": 202,
            "customer_id": 303,
            "active_goal_id": "goal:0123456789abcdef",
            "stage": "QUALIFICATION",
            "stage_confidence": 0.75,
            "next_best_action": "ASK_CLARIFICATION",
            "planning_flags": {"explicit_purchase_intent": True},
            "state_version": 1,
            "updated_at": datetime.now(timezone.utc),
            "unknown": "no",
        })

    too_large = {"oversized": "x" * 4096}
    with pytest.raises(ValueError, match="size limit"):
        from app.services.sales_journey_adapter import _validate_json_envelope_size

        _validate_json_envelope_size(too_large)


def test_metadata_sanitizer_preserves_unrelated_metadata_and_drops_journey_diagnostics():
    payload = serialize_state(_runtime_state())
    incoming = {
        "trace_id": "trace-safe",
        JOURNEY_STATE_METADATA_KEY: payload,
        "sales_journey_transition_reason": "contains customer free text",
    }
    safe_without_auth = sanitize_journey_metadata(incoming)
    assert safe_without_auth == {"trace_id": "trace-safe"}

    safe = sanitize_journey_metadata(incoming, allow_state=True)
    assert safe["trace_id"] == "trace-safe"
    assert safe[JOURNEY_STATE_METADATA_KEY] == payload
    assert "sales_journey_transition_reason" not in safe


def test_blank_purpose_policy_fails_closed_without_consent_database_lookup(monkeypatch):
    class NoQuery:
        def query(self, *args, **kwargs):
            raise AssertionError("missing policy must fail before consent lookup")

    monkeypatch.setattr(settings, "SALES_JOURNEY_PERSISTENCE_PURPOSE", "")
    monkeypatch.setattr(settings, "SALES_JOURNEY_PERSISTENCE_POLICY_VERSION", "")
    result = authorize_journey_persistence(
        NoQuery(),
        business_id=101,
        customer_id=303,
        purpose=settings.SALES_JOURNEY_PERSISTENCE_PURPOSE,
        policy_version=settings.SALES_JOURNEY_PERSISTENCE_POLICY_VERSION,
    )
    assert not result.allowed
    assert result.status == "policy_decision_required"


@pytest.mark.parametrize(
    "consent_values",
    [
        {"status": "denied"},
        {"status": "revoked", "revoked_at": datetime.now(timezone.utc)},
        {"status": "granted", "version": "v2"},
        {"status": "granted", "purpose": "marketing"},
    ],
)
def test_consent_is_purpose_version_and_revocation_specific(consent_db, monkeypatch, consent_values):
    _valid_settings(monkeypatch)
    db, customer_id, _ = consent_db
    _add_consent(db, customer_id, **consent_values)
    result = authorize_journey_persistence(
        db,
        business_id=101,
        customer_id=customer_id,
        purpose="sales_journey_context",
        policy_version="v1",
    )
    assert not result.allowed


def test_newer_revocation_invalidates_an_older_grant(consent_db, monkeypatch):
    _valid_settings(monkeypatch)
    db, customer_id, _ = consent_db
    _add_consent(db, customer_id)
    _add_consent(db, customer_id, status="revoked", revoked_at=datetime.now(timezone.utc))
    result = authorize_journey_persistence(
        db,
        business_id=101,
        customer_id=customer_id,
        purpose="sales_journey_context",
        policy_version="v1",
    )
    assert not result.allowed


def test_locked_journey_write_serializes_on_customer_before_consent_lookup():
    from app.models.customer import Customer
    from app.services.sales_journey_privacy import authorize_journey_persistence

    customer_query = Mock()
    customer_query.filter.return_value = customer_query
    customer_query.populate_existing.return_value = customer_query
    customer_query.with_for_update.return_value = customer_query
    customer_query.first.return_value = SimpleNamespace(id=303, business_id=101)

    consent_query = Mock()
    consent_query.filter.return_value = consent_query
    consent_query.order_by.return_value = consent_query
    consent_query.with_for_update.return_value = consent_query
    consent_query.first.return_value = SimpleNamespace(
        status="granted", revoked_at=None, policy_version="v1",
    )

    db = Mock()
    db.query.side_effect = [customer_query, consent_query]
    result = authorize_journey_persistence(
        db,
        business_id=101,
        customer_id=303,
        purpose="sales_journey_context",
        policy_version="v1",
        lock_consent=True,
    )

    assert result.allowed
    assert [call.args[0] for call in db.query.call_args_list] == [Customer, CustomerConsent]
    customer_query.with_for_update.assert_called_once_with()
    consent_query.with_for_update.assert_called_once_with()


def test_optional_consent_policy_still_blocks_explicit_revocation(consent_db, monkeypatch):
    _valid_settings(monkeypatch)
    monkeypatch.setattr(settings, "SALES_JOURNEY_PERSISTENCE_REQUIRES_CONSENT", False)
    db, customer_id, conversation_id = consent_db
    _add_consent(db, customer_id, status="revoked", revoked_at=datetime.now(timezone.utc))

    payload = serialize_state(_runtime_state(conversation_id=conversation_id, customer_id=customer_id))
    filtered = filter_journey_metadata_for_persistence(
        db,
        {JOURNEY_STATE_METADATA_KEY: payload, "trace": "safe"},
        business_id=101,
        conversation_id=conversation_id,
        customer_id=customer_id,
    )

    assert filtered == {"trace": "safe"}


def test_granted_consent_allows_only_fresh_state_in_exact_customer_tenant_and_conversation_scope(
    consent_db, monkeypatch
):
    _valid_settings(monkeypatch)
    db, customer_id, conversation_id = consent_db
    _add_consent(db, customer_id)
    metadata = {
        "trace_id": "safe-trace",
        JOURNEY_STATE_METADATA_KEY: serialize_state(
            _runtime_state(tenant_id=101, conversation_id=conversation_id, customer_id=customer_id)
        ),
        "sales_journey_debug": "unsafe diagnostic",
    }

    safe = filter_journey_metadata_for_persistence(
        db,
        metadata,
        business_id=101,
        conversation_id=conversation_id,
        customer_id=customer_id,
    )
    assert safe["trace_id"] == "safe-trace"
    assert JOURNEY_STATE_METADATA_KEY in safe
    assert "sales_journey_debug" not in safe

    cross_scope = filter_journey_metadata_for_persistence(
        db,
        metadata,
        business_id=101,
        conversation_id=conversation_id + 1,
        customer_id=customer_id,
    )
    assert cross_scope == {"trace_id": "safe-trace"}


def test_revoke_removes_state_from_subsequent_write_metadata(consent_db, monkeypatch):
    _valid_settings(monkeypatch)
    db, customer_id, conversation_id = consent_db
    _add_consent(db, customer_id)
    metadata = {
        "trace_id": "safe-trace",
        JOURNEY_STATE_METADATA_KEY: serialize_state(
            _runtime_state(tenant_id=101, conversation_id=conversation_id, customer_id=customer_id)
        ),
    }
    _add_consent(db, customer_id, status="revoked", revoked_at=datetime.now(timezone.utc))
    safe = filter_journey_metadata_for_persistence(
        db,
        metadata,
        business_id=101,
        conversation_id=conversation_id,
        customer_id=customer_id,
    )
    assert safe == {"trace_id": "safe-trace"}


def test_explicit_no_consent_policy_requires_configuration_but_no_consent_row(monkeypatch):
    class NoQuery:
        def query(self, *args, **kwargs):
            raise AssertionError("explicit no-consent policy does not query a consent table")

    result = authorize_journey_persistence(
        NoQuery(),
        business_id=101,
        customer_id=None,
        purpose="essential_turn_context",
        policy_version="approved-v1",
        requires_consent=False,
    )
    assert result.allowed
    assert result.status == "policy_authorized_without_consent"


def test_message_metadata_formatter_denies_journey_state_without_write_authorization():
    from app.services.auto_reply_service import _reply_metadata

    safe = _reply_metadata(
        [],
        None,
        {
            "trace_id": "trace-safe",
            JOURNEY_STATE_METADATA_KEY: serialize_state(_runtime_state()),
            "sales_journey_reason": "raw text",
        },
    )
    assert safe["trace_id"] == "trace-safe"
    assert not any(key.startswith("sales_journey_") for key in safe)


def test_both_production_metadata_writers_call_the_privacy_gate_before_persisting():
    root = Path(__file__).parents[1]
    turn_tree = ast.parse((root / "app" / "services" / "conversation_turn_service.py").read_text(encoding="utf-8"))
    reply_tree = ast.parse((root / "app" / "services" / "auto_reply_service.py").read_text(encoding="utf-8"))

    def function_node(tree, name):
        return next(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)

    def call_line(node, name):
        return min(
            child.lineno
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == name
        )

    turn = function_node(turn_tree, "dispatch_chatbot_turn")
    outbound = function_node(reply_tree, "_save_auto_reply_outbound")
    assert call_line(turn, "filter_journey_metadata_for_persistence") < min(
        child.lineno for child in ast.walk(turn) if isinstance(child, ast.Attribute) and child.attr == "payload"
    )
    assert call_line(outbound, "filter_journey_metadata_for_persistence") < min(
        child.lineno for child in ast.walk(outbound) if isinstance(child, ast.Attribute) and child.attr == "metadata_"
    )
