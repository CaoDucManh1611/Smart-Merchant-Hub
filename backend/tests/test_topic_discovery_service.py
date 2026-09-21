from types import SimpleNamespace

from app.services.topic_discovery_service import discover_topic_suggestions


def _message(identifier: int, conversation_id: int, content: str, metadata=None):
    return SimpleNamespace(
        id=identifier,
        conversation_id=conversation_id,
        content=content,
        metadata_=metadata,
    )


def test_discovers_reviewable_topics_without_mutating_knowledge_base():
    result = discover_topic_suggestions([
        _message(1, 11, "Shop có giao hàng về Hà Nội không?"),
        _message(2, 12, "Phí giao hàng và vận chuyển là bao nhiêu?"),
        _message(3, 13, "Tôi muốn đổi trả sản phẩm bị lỗi"),
        _message(4, 14, "Sản phẩm lỗi có được đổi trả không?"),
    ])

    assert result["knowledge_base_updated"] is False
    assert result["messages_analyzed"] == 4
    assert result["suggestions"]
    assert all(item["review_status"] == "pending_review" for item in result["suggestions"])
    assert all(item["source"] == "deterministic_local_embedding" for item in result["suggestions"])


def test_uses_consistent_stored_embeddings_when_available():
    result = discover_topic_suggestions([
        _message(1, 11, "giao hàng", {"topic_embedding": [1.0, 0.0]}),
        _message(2, 12, "phí ship", {"topic_embedding": [0.99, 0.01]}),
        _message(3, 13, "bảo hành", {"topic_embedding": [0.0, 1.0]}),
        _message(4, 14, "đổi trả", {"topic_embedding": [0.01, 0.99]}),
    ])

    assert len(result["suggestions"]) == 2
    assert all(item["source"] == "stored_embeddings" for item in result["suggestions"])


def test_mixed_or_invalid_stored_embeddings_fall_back_safely():
    result = discover_topic_suggestions([
        _message(1, 11, "giao hàng", {"topic_embedding": [1.0, 0.0]}),
        _message(2, 12, "giao hàng nhanh", {"topic_embedding": [float("nan"), 1.0]}),
    ])

    assert result["suggestions"][0]["source"] == "deterministic_local_embedding"
