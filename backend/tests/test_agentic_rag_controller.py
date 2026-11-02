from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.business_setting import BusinessSetting
from app.rag.agentic_controller import (
    corrective_query,
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


def test_corrective_query_adds_terms_without_removing_customer_constraints():
    query = "Áo mưa SKU AO-XL size XL còn hàng không?"

    expanded = corrective_query(query)

    assert query in expanded
    assert "SKU AO-XL" in expanded
    assert "size XL" in expanded
    assert "số lượng còn hàng" in expanded


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
