from app.services import ingestion_service
from app.rag.embedder import embedding_retry_delay


def test_embedding_failure_keeps_chunks_lexically_searchable(monkeypatch):
    def fail(_contents):
        raise RuntimeError("embedding quota exhausted")

    monkeypatch.setattr(ingestion_service, "embed_texts", fail)

    embeddings, used_embeddings = ingestion_service.embed_chunks_or_fallback(
        ["Serum Vitamin C giá 420.000 đồng"]
    )

    assert embeddings == [None]
    assert used_embeddings is False


def test_embedding_quota_error_exposes_retry_delay(monkeypatch):
    captured = []

    def fail(_contents):
        raise RuntimeError("429 RESOURCE_EXHAUSTED; retry_delay { seconds: 7 }")

    monkeypatch.setattr(ingestion_service, "embed_texts", fail)

    embeddings, used_embeddings = ingestion_service.embed_chunks_or_fallback(
        ["Áo thun"],
        on_error=captured.append,
    )

    assert embeddings == [None]
    assert used_embeddings is False
    assert len(captured) == 1
    assert embedding_retry_delay(captured[0]) == 8


def test_embedding_retry_delay_ignores_permanent_errors():
    assert embedding_retry_delay(RuntimeError("invalid model name")) is None
