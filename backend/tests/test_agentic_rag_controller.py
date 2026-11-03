from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.business_setting import BusinessSetting
from app.rag.agentic_controller import (
    corrective_query,
    corrective_retry_decision,
    evidence_quality,
    load_rag_runtime_options,
    retrieval_is_weak,
)


def test_agentic_and_retrieval_flags_are_independent_per_shop(monkeypatch):
    engine = create_engine("sqlite://")
    BusinessSetting.__table__.create(engine)
    monkeypatch.setattr(settings, "RAG_RETRIEVAL_MODE", "bm25")
    monkeypatch.setattr(settings, "RAG_AGENTIC_ENABLED", False)
    monkeypatch.setattr(settings, "RAG_AGENTIC_MODE", "off")
    monkeypatch.setattr(settings, "RAG_EXPERIMENTAL_SERVING_ENABLED", True)
    with Session(engine) as db:
        db.add_all([
            BusinessSetting(business_id=41, key="rag_retrieval_mode", value="hybrid"),
            BusinessSetting(business_id=41, key="rag_agentic_mode", value="active"),
            BusinessSetting(business_id=42, key="rag_agentic_mode", value="decision_shadow"),
        ])
        db.commit()

        shop_41 = load_rag_runtime_options(db, 41)
        shop_42 = load_rag_runtime_options(db, 42)

    assert (shop_41.retrieval_mode, shop_41.agentic_mode) == ("hybrid", "active")
    assert (shop_42.retrieval_mode, shop_42.agentic_mode) == ("bm25", "decision_shadow")
    assert shop_42.agentic_enabled
    engine.dispose()


def test_experimental_shop_overrides_are_ignored_by_default(monkeypatch):
    engine = create_engine("sqlite://")
    BusinessSetting.__table__.create(engine)
    monkeypatch.setattr(settings, "RAG_RETRIEVAL_MODE", "hybrid")
    monkeypatch.setattr(settings, "RAG_AGENTIC_ENABLED", True)
    monkeypatch.setattr(settings, "RAG_AGENTIC_MODE", "active")
    monkeypatch.setattr(settings, "RAG_EXPERIMENTAL_SERVING_ENABLED", False)
    with Session(engine) as db:
        db.add_all([
            BusinessSetting(business_id=41, key="rag_retrieval_mode", value="auto"),
            BusinessSetting(business_id=41, key="rag_agentic_mode", value="active"),
        ])
        db.commit()

        with patch.object(db, "query", wraps=db.query) as query:
            options = load_rag_runtime_options(db, 41)

    assert options.retrieval_mode == "bm25"
    assert options.agentic_mode == "off"
    assert not options.agentic_enabled
    query.assert_not_called()
    engine.dispose()


def test_corrective_query_adds_terms_without_removing_customer_constraints():
    query = "Áo mưa SKU AO-XL size XL còn hàng không?"

    expanded = corrective_query(query)

    assert query in expanded
    assert "SKU AO-XL" in expanded
    assert "size XL" in expanded
    assert "số lượng còn hàng" in expanded


def test_corrective_query_preserves_long_questions_instead_of_cutting_constraints():
    query = f"Mã hàng {'X' * 1250} còn hàng không?"
    expanded = corrective_query(query)

    assert expanded.startswith(query)
    assert expanded.endswith("trạng thái bán")


def test_corrective_query_distinguishes_delivery_time_from_price():
    expanded = corrective_query("Giao mấy ngày thì nhận được?")

    assert "thời gian giao hàng" in expanded
    assert "đơn giá" not in expanded


def test_corrective_retry_decision_reports_why_it_skips_or_retries():
    class Chunk:
        def __init__(self, similarity):
            self.similarity = similarity

    shared = {
        "has_image": False,
        "is_casual": False,
        "tool_calls": 1,
        "max_tool_calls": 4,
        "elapsed_seconds": 0.2,
        "timeout_seconds": 8.0,
        "threshold": 0.3,
    }

    assert corrective_retry_decision(
        "Hàng này giá bao nhiêu?", [], agentic_mode="off", **shared,
    ) == (False, "agentic_mode_off", None)
    assert corrective_retry_decision(
        "Hàng này giá bao nhiêu?", [], agentic_mode="active", **(shared | {"has_image": True}),
    ) == (False, "image_query_excluded", None)
    assert corrective_retry_decision(
        "Hàng này giá bao nhiêu?", [Chunk(0.8)], agentic_mode="active", **shared,
    ) == (False, "retrieval_above_threshold", None)
    assert corrective_retry_decision(
        "Chào bạn", [], agentic_mode="active", **(shared | {"is_casual": True}),
    ) == (False, "casual_query_excluded", None)
    assert corrective_retry_decision(
        "Hàng này giá bao nhiêu?", [], agentic_mode="active", **(shared | {"tool_calls": 4}),
    ) == (False, "tool_call_budget_exhausted", None)
    assert corrective_retry_decision(
        "Hàng này giá bao nhiêu?", [], agentic_mode="active",
        **(shared | {"elapsed_seconds": 8.0}),
    ) == (False, "timeout_budget_exhausted", None)
    should_retry, reason, retry_query = corrective_retry_decision(
        "Hàng này giá bao nhiêu?", [], agentic_mode="active", **shared,
    )
    assert should_retry
    assert reason == "weak_retrieval_retry_eligible"
    assert "giá hiện hành" in retry_query


def test_corrective_retry_decision_skips_weak_query_without_matching_expansion():
    decision = corrective_retry_decision(
        "Xin tư vấn giúp mình.",
        [],
        agentic_mode="active",
        has_image=False,
        is_casual=False,
        tool_calls=1,
        max_tool_calls=4,
        elapsed_seconds=0.2,
        timeout_seconds=8.0,
        threshold=0.3,
    )

    assert decision == (False, "no_corrective_expansion", None)


def test_weak_retrieval_and_quality_selection_are_deterministic():
    class Chunk:
        def __init__(self, similarity, retrieval_scores=None):
            self.similarity = similarity
            self.retrieval_scores = retrieval_scores or {}

    assert retrieval_is_weak([], 0.3)
    assert retrieval_is_weak([Chunk(0.29)], 0.3)
    assert not retrieval_is_weak([Chunk(0.3)], 0.3)
    assert evidence_quality([Chunk(0.8)]) > evidence_quality([Chunk(0.7), Chunk(0.6)])
    assert evidence_quality([Chunk(0.8, {"rrf_adjusted_score": 0.04})]) == (0.04, 0.04)
    assert evidence_quality([Chunk(0.9), Chunk(0.5), Chunk(0.4), Chunk(0.1)]) == (0.9, 0.6)
