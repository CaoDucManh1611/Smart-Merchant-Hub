from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.bases import TenantBase
from app.models.business import Business
from app.models.document import Document, DocumentChunk
from app.models.recommendation_catalog import (
    RecommendationCatalogAttribute,
    RecommendationCatalogChunkMapping,
    RecommendationCatalogEntry,
)
from app.rag.retriever import retrieve


def test_exact_sku_variant_question_retrieves_the_comparison_evidence_too():
    engine = create_engine("sqlite://")
    Business.metadata.create_all(engine)
    TenantBase.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add(Business(id=70101, name="Synthetic Aster", slug="synthetic-aster"))
            db.add(Business(id=70102, name="Synthetic Other", slug="synthetic-other"))
            db.flush()
            mini = Document(
                business_id=70101, filename="mini.txt", file_type="txt",
                file_size=1, status="ready",
            )
            full = Document(
                business_id=70101, filename="full.txt", file_type="txt",
                file_size=1, status="ready",
            )
            db.add_all([mini, full])
            db.flush()
            db.add_all([
                DocumentChunk(
                    document_id=mini.id,
                    content="Aster desk lamp mini, 300 lumen brightness, SKU AST-LAMP-MINI-01.",
                    chunk_index=0,
                    metadata_={"topic": "products", "benchmark_evidence_id": "aster:lamp-mini"},
                ),
                DocumentChunk(
                    document_id=full.id,
                    content="Aster desk lamp full, 700 lumen brightness, SKU AST-LAMP-FULL-01.",
                    chunk_index=0,
                    metadata_={"topic": "products", "benchmark_evidence_id": "aster:lamp-full"},
                ),
            ])
            foreign = Document(
                business_id=70102, filename="foreign-full.txt", file_type="txt",
                file_size=1, status="ready",
            )
            db.add(foreign)
            db.flush()
            db.add(DocumentChunk(
                document_id=foreign.id,
                content="Aster desk lamp full, 900 lumen brightness, SKU AST-FOREIGN-FULL-01.",
                chunk_index=0,
                metadata_={"topic": "products", "benchmark_evidence_id": "foreign:lamp-full"},
            ))
            db.commit()

            results = retrieve(
                "What is SKU AST-LAMP-MINI-01 and is it the full lamp?",
                db,
                business_id=70101,
                top_k=5,
                retrieval_mode="bm25",
            )

            evidence_ids = [
                str((item.metadata or {}).get("benchmark_evidence_id") or "")
                for item in results
            ]
            assert evidence_ids[:2] == ["aster:lamp-mini", "aster:lamp-full"]

            exact_only = retrieve(
                "What is SKU AST-LAMP-MINI-01?",
                db,
                business_id=70101,
                top_k=5,
                retrieval_mode="bm25",
            )
            assert [
                str((item.metadata or {}).get("benchmark_evidence_id") or "")
                for item in exact_only
            ] == ["aster:lamp-mini"]

            caller_constrained = retrieve(
                "What is SKU AST-LAMP-MINI-01 and is it the full lamp?",
                db,
                business_id=70101,
                top_k=5,
                hard_filters={"sku": "AST-LAMP-MINI-01"},
                retrieval_mode="bm25",
            )
            assert [
                str((item.metadata or {}).get("benchmark_evidence_id") or "")
                for item in caller_constrained
            ] == ["aster:lamp-mini"]

            unknown_sku = retrieve(
                "What is SKU AST-LAMP-UNKNOWN-99 and is it the full lamp?",
                db,
                business_id=70101,
                top_k=5,
                retrieval_mode="bm25",
            )
            assert unknown_sku == []

            assert all(item.document_id != foreign.id for item in results)
    finally:
        engine.dispose()


def test_vietnamese_mirror_variant_question_supports_an_unseen_sku_format():
    engine = create_engine("sqlite://")
    Business.metadata.create_all(engine)
    TenantBase.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add(Business(id=70111, name="Synthetic Mirror Shop", slug="synthetic-mirror"))
            db.flush()
            left_doc = Document(
                business_id=70111, filename="mirror-left.txt", file_type="txt",
                file_size=1, status="ready",
            )
            right_doc = Document(
                business_id=70111, filename="mirror-right.txt", file_type="txt",
                file_size=1, status="ready",
            )
            db.add_all([left_doc, right_doc])
            db.flush()
            db.add_all([
                DocumentChunk(
                    document_id=left_doc.id,
                    content="Gương chiếu hậu ren M10 bên trái, SKU AST-MIRROR-M10-L.",
                    chunk_index=0,
                    metadata_={"topic": "products", "sku": "AST-MIRROR-M10-L", "benchmark_evidence_id": "mirror:left"},
                ),
                DocumentChunk(
                    document_id=right_doc.id,
                    content="Gương chiếu hậu ren M10 bên phải, SKU AST-MIRROR-M10-R.",
                    chunk_index=0,
                    metadata_={"topic": "products", "sku": "AST-MIRROR-M10-R", "benchmark_evidence_id": "mirror:right"},
                ),
            ])
            db.commit()

            results = retrieve(
                "Mã AST-MIRROR-M10-L có phải gương bên phải không?",
                db,
                business_id=70111,
                top_k=5,
                retrieval_mode="bm25",
            )

            evidence_ids = [
                str((item.metadata or {}).get("benchmark_evidence_id") or "")
                for item in results
            ]
            assert evidence_ids[:2] == ["mirror:left", "mirror:right"]
    finally:
        engine.dispose()
