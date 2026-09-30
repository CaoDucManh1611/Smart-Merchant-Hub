from app.services import ingestion_service
from app.rag.embedder import embedding_retry_delay
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models import Business, Document


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


def test_lexical_only_document_keeps_embedding_retry_time(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Business.metadata.create_all(engine)

    def fail(_contents, progress_callback=None):
        raise RuntimeError("embedding temporarily unavailable")

    monkeypatch.setattr(ingestion_service, "embed_texts", fail)
    monkeypatch.setattr(ingestion_service, "embedding_retry_delay", lambda _error: 30)
    with Session(engine) as db:
        doc = Document(filename="retry.txt", file_type="txt", status="pending")
        db.add(doc)
        db.commit()
        ingestion_service.ingest_document(
            doc.id, b"Reliable knowledge for a product.", "retry.txt", db,
        )
        db.refresh(doc)
        assert doc.status == "ready"
        assert doc.embedding_status == "lexical_only"
        assert doc.chunk_count > 0
        assert doc.retry_after > datetime.now(timezone.utc).replace(tzinfo=None)


def test_quota_rejected_document_does_not_publish_catalog_products(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Business.metadata.create_all(engine)
    sync = Mock()
    monkeypatch.setattr(ingestion_service, "sync_catalog_products", sync)
    monkeypatch.setattr(
        ingestion_service, "check_quota",
        lambda *_args, **_kwargs: SimpleNamespace(allowed=False, used=10, limit=10),
    )
    with Session(engine) as db:
        business = Business(name="Fixture shop", slug="fixture-rag-shop")
        db.add(business)
        db.flush()
        doc = Document(business_id=business.id, filename="catalog.txt", file_type="txt", status="pending")
        db.add(doc)
        db.commit()
        ingestion_service.ingest_document(
            doc.id, b"Product SKU-123 costs 10000 VND.", "catalog.txt", db,
            business_id=business.id,
        )
        db.refresh(doc)
        assert doc.status == "error"
        assert doc.error_code == "chunk_quota_exceeded"
    sync.assert_not_called()
