"""Offline regression gates for index publication, catalog and tenant guards."""
from datetime import datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Business, CrmJob, Document, DocumentChunk, DocumentIndexSnapshot, RagRun
from app.models.business import ServicePlan, Subscription, User
from app.models.recommendation_catalog import RecommendationCatalogChunkMapping, RecommendationCatalogEntry
from app.models.saas import SaaSUsage
from app.services import ingestion_service as ingestion
from app.services import document_index_snapshot_service as snapshots
from app.services.quota_service import QuotaDecision, QuotaExceededError, quota_period_start
from app.services.rag_job_service import dispatch_rag_job
from app.services.recommendation_catalog_service import sync_product_catalog_entry
from app.services.document_index_snapshot_service import restore_index_snapshot
from app.models.sales import Product
from scripts.audit_safe_reindex import audit_documents, main as audit_main


SOURCE = b"- Bottle A (SKU A-001): price 10000.\n- Bottle B (SKU B-002): price 20000."


@pytest.fixture
def db(monkeypatch, tmp_path):
    monkeypatch.setattr(ingestion.settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(ingestion.settings, "GEMINI_API_KEYS", "")
    monkeypatch.setattr(ingestion.settings, "EMBEDDING_PROVIDER", "local")
    monkeypatch.setattr(ingestion.settings, "RAG_LOG_FILE", str(tmp_path / "rag.jsonl"))
    # No real embedding or chunking call can leave these tests.
    monkeypatch.setattr(ingestion, "call_gemini_for_chunking", Mock(side_effect=AssertionError("network forbidden")))
    monkeypatch.setattr(ingestion, "embed_texts", lambda texts, **kw: [
        [0.1] * ingestion.settings.EMBEDDING_DIMENSION for _ in texts
    ])
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Business.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Business(id=1, name="One", slug="safe-one"), Business(id=2, name="Two", slug="safe-two")])
        session.commit()
        yield session
    engine.dispose()


def ready_document(db, *, business_id=1, filename="catalog.md", source=SOURCE):
    doc = Document(business_id=business_id, filename=filename, file_type="md", status="ready",
                   embedding_status="ready", chunk_count=1, source_bytes=source,
                   reindex_count=1, processed_at=datetime(2026, 1, 1))
    db.add(doc)
    db.flush()
    chunk = DocumentChunk(document_id=doc.id, chunk_index=0, content="Old A-001 B-002",
                          embedding=[0.2] * ingestion.settings.EMBEDDING_DIMENSION,
                          metadata_={"revision": "old"})
    db.add(chunk)
    db.flush()
    # PostgreSQL sequences do not reuse deleted IDs; SQLite may reuse rowid.
    # Keep the old fixture object out of its identity map during replacement.
    db.expunge(chunk)
    return doc, chunk


def catalog_fixture(db):
    doc, old = ready_document(db)
    product = Product(business_id=1, sku="A-001", name="Current bottle", price=Decimal("98765"),
                      stock_quantity=3, reserved_quantity=1, status="inactive",
                      metadata_={"catalog_source": "knowledge_document", "catalog_source_document_id": doc.id})
    db.add(product)
    db.flush()
    sync_product_catalog_entry(db, product, document_chunk_ids=[old.id])
    db.commit()
    return doc, old, product


def index_snapshot(db, doc):
    db.refresh(doc)
    chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc.id).order_by(DocumentChunk.id)).all()
    links = db.execute(select(RecommendationCatalogChunkMapping.catalog_entry_id,
                             RecommendationCatalogChunkMapping.document_chunk_id)
                       .where(RecommendationCatalogChunkMapping.document_chunk_id.in_([c.id for c in chunks]))).all()
    return (doc.status, doc.embedding_status, doc.chunk_count, doc.processed_at, doc.retry_after,
            [(c.id, c.content, list(c.embedding) if c.embedding is not None else None, c.metadata_) for c in chunks], links)


def assert_product_unchanged(db, product):
    db.refresh(product)
    assert (product.price, product.stock_quantity, product.reserved_quantity, product.status) == (
        Decimal("98765"), 3, 1, "inactive",
    )


def execute(db, doc, **kwargs):
    return ingestion.ingest_document(doc.id, bytes(doc.source_bytes), doc.filename, db,
                                     business_id=doc.business_id, **kwargs)


@pytest.mark.parametrize("explicit_mode", [True, False])
def test_reindex_preserves_live_product_and_rebuilds_links(db, monkeypatch, explicit_mode):
    doc, old, product = catalog_fixture(db)
    other, other_chunk = ready_document(db, filename="other.md")
    foreign, foreign_chunk = ready_document(db, business_id=2, filename="foreign.md")
    other_product = Product(business_id=2, sku="A-001", name="Other shop", price=1, stock_quantity=9)
    db.add(other_product)
    db.flush()
    sync_product_catalog_entry(db, product, document_chunk_ids=[old.id, other_chunk.id])
    sync_product_catalog_entry(db, other_product, document_chunk_ids=[foreign_chunk.id])
    db.commit()
    foreign_before = index_snapshot(db, foreign)
    sync = Mock(side_effect=AssertionError("reindex must not import catalog"))
    monkeypatch.setattr(ingestion, "sync_catalog_products", sync)
    assert execute(db, doc, reindex_only=explicit_mode) is True
    sync.assert_not_called()
    assert_product_unchanged(db, product)
    entry = db.scalar(select(RecommendationCatalogEntry).where(RecommendationCatalogEntry.business_id == 1))
    assert (entry.price, entry.stock_quantity, entry.status) == (Decimal("98765"), Decimal("2"), "inactive")
    links = db.scalars(select(RecommendationCatalogChunkMapping.document_chunk_id).where(
        RecommendationCatalogChunkMapping.catalog_entry_id == entry.id,
    )).all()
    assert other_chunk.id in links
    linked_content = db.scalars(select(DocumentChunk.content).where(DocumentChunk.id.in_(links))).all()
    assert any("Bottle A" in content for content in linked_content)
    assert index_snapshot(db, foreign) == foreign_before


@pytest.mark.parametrize("failure", ["load", "empty", "embedding", "bad_vectors", "mapping", "commit"])
def test_failed_reindex_preserves_ready_index_mappings_and_prices(db, monkeypatch, failure):
    doc, old, product = catalog_fixture(db)
    before = index_snapshot(db, doc)
    if failure == "load":
        monkeypatch.setattr(ingestion, "load_document", Mock(side_effect=RuntimeError("bad loader")))
    elif failure == "empty":
        monkeypatch.setattr(ingestion, "chunk_document", lambda **kw: [])
    elif failure == "embedding":
        monkeypatch.setattr(ingestion, "embed_texts", Mock(side_effect=RuntimeError("429 retry later")))
    elif failure == "bad_vectors":
        monkeypatch.setattr(ingestion, "embed_texts", lambda *a, **kw: [])
    elif failure == "mapping":
        monkeypatch.setattr(ingestion, "sync_product_catalog_entry", Mock(side_effect=RuntimeError("mapping failed")))
    else:
        commit = db.commit
        def fail_publication_once():
            if doc.processed_at != datetime(2026, 1, 1):
                monkeypatch.setattr(db, "commit", commit)
                raise RuntimeError("store commit failed")
            commit()
        monkeypatch.setattr(db, "commit", fail_publication_once)
    assert execute(db, doc, reindex_only=True) is False
    assert index_snapshot(db, doc) == before
    assert doc.error_code in {"empty_document", "document_processing_failed"}
    assert_product_unchanged(db, product)


def set_chunk_limit(db, limit):
    plan = ServicePlan(code="safe-plan", name="Safe", max_rag_chunks=limit)
    db.add(plan)
    db.flush()
    db.add(Subscription(business_id=1, plan_id=plan.id, status="active"))
    db.add(SaaSUsage(business_id=1, resource="rag_chunks", period_start=quota_period_start(), used=1))
    db.commit()


@pytest.mark.parametrize("failure", ["preflight", "reservation", "ai"])
def test_quota_failure_keeps_old_index_and_prices(db, monkeypatch, failure):
    doc, old, product = catalog_fixture(db)
    before = index_snapshot(db, doc)
    set_chunk_limit(db, 1 if failure == "preflight" else 10)
    embed = Mock(wraps=ingestion.embed_texts)
    monkeypatch.setattr(ingestion, "embed_texts", embed)
    error = QuotaExceededError(QuotaDecision(False, "rag_chunks", Decimal(10), Decimal(10), Decimal(1), quota_period_start()))
    if failure == "reservation":
        def reject(*args, **kwargs):
            # The authoritative reservation rejects before old rows are removed.
            assert index_snapshot(db, doc) == before
            raise error
        monkeypatch.setattr(ingestion, "reserve_quota", reject)
    elif failure == "ai":
        monkeypatch.setattr(ingestion.settings, "EMBEDDING_PROVIDER", "gemini")
        monkeypatch.setattr(ingestion, "reserve_ai_budget", Mock(side_effect=error))
    assert execute(db, doc, reindex_only=True) is False
    assert index_snapshot(db, doc) == before
    assert_product_unchanged(db, product)
    assert doc.error_code == ("ai_quota_exceeded" if failure == "ai" else "chunk_quota_exceeded")
    assert db.scalar(select(SaaSUsage.used).where(SaaSUsage.resource == "rag_chunks")) == 1
    if failure != "reservation":
        embed.assert_not_called()


def test_quota_delta_is_reserved_once_and_released_on_shrink(db):
    doc, old, product = catalog_fixture(db)
    set_chunk_limit(db, 3)
    assert execute(db, doc) is True
    assert doc.chunk_count == 2
    assert db.scalar(select(SaaSUsage.used).where(SaaSUsage.resource == "rag_chunks")) == 2
    assert execute(db, doc) is True
    assert db.scalar(select(SaaSUsage.used).where(SaaSUsage.resource == "rag_chunks")) == 2
    doc.source_bytes = b"- Bottle A (SKU A-001): price 10000."
    db.commit()
    assert execute(db, doc) is True
    assert db.scalar(select(SaaSUsage.used).where(SaaSUsage.resource == "rag_chunks")) == 1
    assert_product_unchanged(db, product)


def test_failed_store_rolls_back_local_quota_reservation(db, monkeypatch):
    doc, old, product = catalog_fixture(db)
    set_chunk_limit(db, 3)
    monkeypatch.setattr(ingestion, "sync_product_catalog_entry", Mock(side_effect=RuntimeError("store failed")))
    assert execute(db, doc) is False
    assert db.scalar(select(SaaSUsage.used).where(SaaSUsage.resource == "rag_chunks")) == 1


@pytest.mark.parametrize("outcome", ["success", "mapping", "commit", "quota"])
def test_separate_control_plane_quota_is_reserved_before_publish_and_compensated(db, monkeypatch, outcome):
    from app.database.bases import PlatformBase
    from app.database import platform_session
    from app.database.platform_session import PlatformSession
    from app.models.platform_control import PlatformBusiness, PlatformServicePlan, PlatformSubscription, PlatformUsage

    doc, old, product = catalog_fixture(db)
    before = index_snapshot(db, doc)
    engine = create_engine("sqlite://")
    PlatformBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=PlatformSession)
    monkeypatch.setattr(platform_session, "PlatformSessionLocal", factory)
    with factory() as control:
        control.add(PlatformBusiness(id=1, name="One", slug="one"))
        control.add(PlatformServicePlan(id=1, code="safe", name="Safe", quotas={"rag_chunks": 1 if outcome == "quota" else 3}))
        control.add(PlatformSubscription(business_id=1, plan_id=1, status="active"))
        control.add(PlatformUsage(business_id=1, resource="rag_chunks", used=1, period_start=quota_period_start()))
        control.commit()
    db.info["tenant_schema"] = "shop_1"
    sync = ingestion.sync_product_catalog_entry
    observed = []
    def inspect_reservation(*args, **kwargs):
        with factory() as control:
            observed.append(control.scalar(select(PlatformUsage.used)))
        if outcome == "mapping":
            raise RuntimeError("mapping failure after external reservation")
        return sync(*args, **kwargs)
    monkeypatch.setattr(ingestion, "sync_product_catalog_entry", inspect_reservation)
    if outcome == "quota":
        # Allow the advisory check, then lose capacity at the locked reservation.
        monkeypatch.setattr(ingestion, "check_quota", lambda *a, **kw: Mock(allowed=True))
    if outcome == "commit":
        commit = db.commit
        def fail_commit_once():
            if doc.processed_at != datetime(2026, 1, 1):
                monkeypatch.setattr(db, "commit", commit)
                raise RuntimeError("tenant commit failure")
            commit()
        monkeypatch.setattr(db, "commit", fail_commit_once)
    try:
        assert execute(db, doc) is (outcome == "success")
        with factory() as control:
            assert control.scalar(select(PlatformUsage.used)) == (2 if outcome == "success" else 1)
        if outcome != "quota":
            assert observed == [2]
        if outcome == "success":
            assert execute(db, doc) is True
            doc.source_bytes = b"- Bottle A (SKU A-001): price 10000."
            db.commit()
            assert execute(db, doc) is True
            with factory() as control:
                assert control.scalar(select(PlatformUsage.used)) == 1
        else:
            assert index_snapshot(db, doc) == before
        assert_product_unchanged(db, product)
    finally:
        engine.dispose()


def test_exact_sku_mapping_does_not_link_prefix_variant(db):
    doc, old, product = catalog_fixture(db)
    doc.source_bytes = b"- Variant (SKU A-001-XL): price 10000."
    db.commit()
    assert execute(db, doc) is True
    entry = db.scalar(select(RecommendationCatalogEntry).where(RecommendationCatalogEntry.business_id == 1))
    assert db.scalar(select(RecommendationCatalogChunkMapping.id).where(
        RecommendationCatalogChunkMapping.catalog_entry_id == entry.id,
    )) is None


def test_initial_ingestion_still_syncs_catalog(db, monkeypatch):
    doc = Document(business_id=1, filename="first.md", file_type="md", source_bytes=SOURCE)
    db.add(doc)
    db.commit()
    sync = Mock(return_value=[])
    monkeypatch.setattr(ingestion, "sync_catalog_products", sync)
    assert execute(db, doc) is True
    sync.assert_called_once()


def test_explicit_reindex_without_old_chunks_never_imports_catalog(db, monkeypatch):
    doc = Document(business_id=1, filename="failed.md", file_type="md", source_bytes=SOURCE, status="error")
    db.add(doc)
    db.commit()
    sync = Mock(side_effect=AssertionError("no catalog import"))
    monkeypatch.setattr(ingestion, "sync_catalog_products", sync)
    assert execute(db, doc, reindex_only=True) is True
    sync.assert_not_called()


def test_worker_records_failure_even_when_old_doc_remains_ready(db, monkeypatch):
    doc, old, product = catalog_fixture(db)
    before = index_snapshot(db, doc)
    run = RagRun(business_id=1, document_id=doc.id, kind="reindex", status="queued")
    db.add(run)
    db.commit()
    monkeypatch.setattr(ingestion, "embed_texts", Mock(side_effect=RuntimeError("provider unavailable")))
    dispatch_rag_job(db, {"run_id": run.id, "document_id": doc.id}, 1)
    assert run.status == "failed" and run.progress_percent == 100
    assert run.error_code == "document_processing_failed"
    assert index_snapshot(db, doc) == before


def test_old_ready_index_is_visible_during_every_progress_commit(db):
    from app.rag.retriever import _retrieve_lexical
    doc, old, product = catalog_fixture(db)
    before = index_snapshot(db, doc)
    seen = []
    def progress(percent, phase, *_):
        db.commit()
        if percent < 100:
            assert index_snapshot(db, doc) == before
            results = _retrieve_lexical("Old", db, 5, business_id=1, similarity_threshold=0)
            assert [result.chunk_id for result in results] == [old.id]
            seen.append(phase)
    assert execute(db, doc, progress_callback=progress) is True
    assert {"load", "chunk", "embed", "store"} <= set(seen)


def test_progress_error_after_publish_does_not_refund_or_hide_new_index(db):
    doc, old, product = catalog_fixture(db)
    set_chunk_limit(db, 3)
    def progress(percent, *_):
        if percent == 100:
            raise RuntimeError("progress polling failed after commit")
    assert execute(db, doc, progress_callback=progress) is True
    db.refresh(doc)
    assert (doc.status, doc.embedding_status, doc.chunk_count) == ("ready", "ready", 2)
    assert db.scalar(select(SaaSUsage.used).where(SaaSUsage.resource == "rag_chunks")) == 2


def test_successful_reindex_creates_restorable_versioned_snapshot(db):
    doc, old, product = catalog_fixture(db)
    set_chunk_limit(db, 3)
    old_content = db.scalar(select(DocumentChunk.content).where(DocumentChunk.document_id == doc.id))
    assert execute(db, doc) is True
    snapshot = db.scalar(select(DocumentIndexSnapshot).where(
        DocumentIndexSnapshot.document_id == doc.id,
        DocumentIndexSnapshot.reason == "pre_publish",
    ))
    assert snapshot is not None and snapshot.business_id == 1 and snapshot.version == 1
    assert snapshot.chunks_payload[0]["content"] == old_content
    assert snapshot.chunks_payload[0]["mappings"]

    restore_index_snapshot(db, business_id=1, document_id=doc.id, snapshot_id=snapshot.id)
    restored = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc.id)).all()
    assert [chunk.content for chunk in restored] == [old_content]
    assert db.scalar(select(RecommendationCatalogChunkMapping.id).where(
        RecommendationCatalogChunkMapping.document_chunk_id == restored[0].id,
    )) is not None
    assert snapshot.restored_at is not None
    assert db.scalar(select(DocumentIndexSnapshot.id).where(
        DocumentIndexSnapshot.document_id == doc.id,
        DocumentIndexSnapshot.reason == "pre_rollback",
    )) is not None
    assert db.scalar(select(SaaSUsage.used).where(SaaSUsage.resource == "rag_chunks")) == 1
    assert_product_unchanged(db, product)


def test_restore_commits_local_quota_release_with_index(db, monkeypatch):
    doc, old, product = catalog_fixture(db)
    set_chunk_limit(db, 3)
    assert execute(db, doc) is True
    snapshot = db.scalar(select(DocumentIndexSnapshot).where(
        DocumentIndexSnapshot.document_id == doc.id,
        DocumentIndexSnapshot.reason == "pre_publish",
    ))
    events = []
    original_release = snapshots.release_quota
    original_commit = db.commit

    def tracked_release(*args, **kwargs):
        events.append("release")
        return original_release(*args, **kwargs)

    def tracked_commit():
        events.append("commit")
        return original_commit()

    monkeypatch.setattr(snapshots, "release_quota", tracked_release)
    monkeypatch.setattr(db, "commit", tracked_commit)
    snapshots.restore_index_snapshot(
        db, business_id=1, document_id=doc.id, snapshot_id=snapshot.id,
    )
    assert events[-2:] == ["release", "commit"]


def test_external_quota_failure_after_restore_does_not_report_index_failure(db, monkeypatch):
    doc, old, product = catalog_fixture(db)
    assert execute(db, doc) is True
    snapshot = db.scalar(select(DocumentIndexSnapshot).where(
        DocumentIndexSnapshot.document_id == doc.id,
        DocumentIndexSnapshot.reason == "pre_publish",
    ))
    db.info["tenant_schema"] = "tenant_1"
    monkeypatch.setattr(
        snapshots, "release_quota", Mock(side_effect=RuntimeError("platform unavailable")),
    )
    restored = snapshots.restore_index_snapshot(
        db, business_id=1, document_id=doc.id, snapshot_id=snapshot.id,
    )
    assert restored.id == snapshot.id
    assert [chunk.content for chunk in db.scalars(
        select(DocumentChunk).where(DocumentChunk.document_id == doc.id)
    ).all()] == [snapshot.chunks_payload[0]["content"]]


def test_repeated_restore_keeps_content_and_quota_reconciled(db):
    doc, old, product = catalog_fixture(db)
    set_chunk_limit(db, 3)
    assert execute(db, doc) is True
    original = db.scalar(select(DocumentIndexSnapshot).where(
        DocumentIndexSnapshot.document_id == doc.id,
        DocumentIndexSnapshot.reason == "pre_publish",
    ))

    snapshots.restore_index_snapshot(
        db, business_id=1, document_id=doc.id, snapshot_id=original.id,
    )
    displaced = db.scalar(select(DocumentIndexSnapshot).where(
        DocumentIndexSnapshot.document_id == doc.id,
        DocumentIndexSnapshot.reason == "pre_rollback",
    ).order_by(DocumentIndexSnapshot.version.desc()))
    assert displaced is not None and len(displaced.chunks_payload) == 2
    assert db.scalar(select(SaaSUsage.used).where(SaaSUsage.resource == "rag_chunks")) == 1

    snapshots.restore_index_snapshot(
        db, business_id=1, document_id=doc.id, snapshot_id=displaced.id,
    )
    assert len(db.scalars(select(DocumentChunk).where(
        DocumentChunk.document_id == doc.id,
    )).all()) == 2
    assert db.scalar(select(SaaSUsage.used).where(SaaSUsage.resource == "rag_chunks")) == 2

    snapshots.restore_index_snapshot(
        db, business_id=1, document_id=doc.id, snapshot_id=original.id,
    )
    assert [chunk.content for chunk in db.scalars(select(DocumentChunk).where(
        DocumentChunk.document_id == doc.id,
    )).all()] == [original.chunks_payload[0]["content"]]
    assert db.scalar(select(SaaSUsage.used).where(SaaSUsage.resource == "rag_chunks")) == 1


def test_snapshot_restore_fails_closed_for_foreign_tenant(db):
    doc, old, product = catalog_fixture(db)
    assert execute(db, doc) is True
    snapshot = db.scalar(select(DocumentIndexSnapshot).where(DocumentIndexSnapshot.document_id == doc.id))
    before = index_snapshot(db, doc)
    with pytest.raises(ValueError, match="snapshot_not_found_for_tenant_document"):
        restore_index_snapshot(db, business_id=2, document_id=doc.id, snapshot_id=snapshot.id)
    assert index_snapshot(db, doc) == before


def test_failed_reindex_does_not_publish_snapshot(db, monkeypatch):
    doc, old, product = catalog_fixture(db)
    monkeypatch.setattr(ingestion, "sync_product_catalog_entry", Mock(side_effect=RuntimeError("mapping failed")))
    assert execute(db, doc) is False
    assert db.scalar(select(DocumentIndexSnapshot.id).where(
        DocumentIndexSnapshot.document_id == doc.id,
    )) is None


def test_worker_guards_tenant_run_document_pair_and_completed_replay(db):
    doc, old, product = catalog_fixture(db)
    other, _ = ready_document(db)
    run = RagRun(business_id=1, document_id=doc.id, kind="reindex", status="queued")
    db.add(run)
    db.commit()
    ingest = Mock()
    dispatch_rag_job(db, {"run_id": run.id, "document_id": doc.id}, 2, ingest_fn=ingest)
    dispatch_rag_job(db, {"run_id": run.id, "document_id": other.id}, 1, ingest_fn=ingest)
    run.status = "completed"
    db.commit()
    dispatch_rag_job(db, {"run_id": run.id, "document_id": doc.id}, 1, ingest_fn=ingest)
    ingest.assert_not_called()


@pytest.fixture
def client(db):
    from app.db.dependencies import get_db
    from app.main import app
    def override():
        yield db
    app.dependency_overrides[get_db] = override
    # Exercise request routing without the production startup/worker lifespan.
    value = TestClient(app)
    try:
        yield value
    finally:
        value.close()
        app.dependency_overrides.clear()


def test_api_queue_keeps_ready_and_rejects_duplicate_and_foreign_tenant(db, client):
    doc, old, product = catalog_fixture(db)
    before = index_snapshot(db, doc)
    url = f"/api/documents/{doc.id}/reindex"
    assert client.post(url, headers={"X-Business-Id": "2"}).status_code == 404
    response = client.post(url, headers={"X-Business-Id": "1"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ready"
    assert index_snapshot(db, doc) == before
    assert client.post(url, headers={"X-Business-Id": "1"}).status_code == 409
    assert db.scalar(select(CrmJob)).payload["reindex_only"] is True


def test_api_retry_keeps_ready_and_mode_across_repeated_retries(db, client):
    doc, old, product = catalog_fixture(db)
    run = RagRun(business_id=1, document_id=doc.id, kind="reindex", status="failed")
    db.add(run)
    db.commit()
    before = index_snapshot(db, doc)
    for _ in range(2):
        response = client.post(f"/api/documents/runs/{run.id}/retry", headers={"X-Business-Id": "1"})
        assert response.status_code == 201, response.text
        run = db.get(RagRun, response.json()["id"])
        assert db.scalar(select(CrmJob).where(CrmJob.payload["run_id"].as_integer() == run.id)).payload["reindex_only"] is True
        assert index_snapshot(db, doc) == before
        run.status = "failed"
        for job in db.scalars(select(CrmJob)).all():
            job.status = "completed"
        db.commit()


@pytest.mark.parametrize("status", ["disabled", "superseded"])
def test_disabled_docs_cannot_be_reindexed_or_retried(db, client, status):
    doc, old, product = catalog_fixture(db)
    doc.status = status
    run = RagRun(business_id=1, document_id=doc.id, kind="reindex", status="failed")
    db.add(run)
    db.commit()
    assert client.post(f"/api/documents/{doc.id}/reindex", headers={"X-Business-Id": "1"}).status_code == 409
    assert client.post(f"/api/documents/runs/{run.id}/retry", headers={"X-Business-Id": "1"}).status_code == 409
    assert execute(db, doc, reindex_only=True) is False


def test_api_write_guard_blocks_viewer(db, client):
    from app.auth.dependencies import get_optional_user
    from app.main import app
    doc, old, product = catalog_fixture(db)
    viewer = User(business_id=1, full_name="Viewer", email="viewer@safe.test", role="viewer", is_active=True)
    db.add(viewer)
    db.commit()
    app.dependency_overrides[get_optional_user] = lambda: viewer
    response = client.post(f"/api/documents/{doc.id}/reindex", headers={"X-Business-Id": "1"})
    assert response.status_code == 403
    assert db.query(RagRun).count() == 0


def test_audit_dry_run_inventory_is_scoped_and_does_not_mutate(db):
    doc, old, product = catalog_fixture(db)
    db.add(Product(business_id=1, sku="B-002", name="B", price=1, stock_quantity=1))
    foreign, _ = ready_document(db, business_id=2)
    db.commit()
    before = index_snapshot(db, doc)
    report = audit_documents(db, business_id=1, document_ids=[doc.id])
    row = report["documents"][0]
    assert report["writes"] == report["network_model_calls"] == 0
    assert report["selected_document_ids"] == [doc.id]
    assert row["multi_sku_chunk_count"] == 1
    assert row["multi_sku_chunks"][0]["content_skus"] == ["a-001", "b-002"]
    assert row["proposed_local_chunks"] == 2 and row["proposed_multi_sku_chunks"] == 0
    assert row["estimated_embedding_tokens"] > 0 and row["estimated_embedding_cost"] is None
    assert index_snapshot(db, doc) == before
    assert not db.new and not db.dirty and not db.deleted
    with pytest.raises(ValueError):
        audit_documents(db, business_id=1, document_ids=[foreign.id])
    with pytest.raises(ValueError):
        audit_documents(db, business_id=1, document_ids=[])


def test_audit_counts_explicit_skus_without_catalog_products(db):
    doc, old = ready_document(db)
    db.query(DocumentChunk).filter_by(id=old.id).update({"content": "SKU UNKNOWN-1 and SKU UNKNOWN-2"})
    db.commit()
    report = audit_documents(db, business_id=1, document_ids=[doc.id])
    assert report["documents"][0]["multi_sku_chunks"][0]["content_skus"] == ["unknown-1", "unknown-2"]


@pytest.mark.parametrize("args", [[], ["--business-id", "1"], ["--business-id", "1", "--document-id", "0"],
                                 ["--business-id", "1", "--document-id", "1", "--apply"]])
def test_audit_cli_requires_explicit_targets_and_has_no_apply(monkeypatch, args):
    monkeypatch.setattr("sys.argv", ["audit_safe_reindex.py", *args])
    with pytest.raises(SystemExit) as error:
        audit_main()
    assert error.value.code == 2
