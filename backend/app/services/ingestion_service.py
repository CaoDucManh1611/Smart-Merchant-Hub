"""
Ingestion Service – orchestrate pipeline: Load → Chunk → Embed → Store.

Chạy như background task để không block request.
"""

import logging
import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document, DocumentChunk
from app.models.sales import Product
from app.models.recommendation_catalog import RecommendationCatalogChunkMapping, RecommendationCatalogEntry
from app.rag.loader import DocumentValidationError, load_document, detect_file_type
from app.rag.semantic_chunker import chunk_document, contextual_embedding_text
from app.rag.semantic_chunker import _parse_model_boundaries
from app.rag.llm_caller import call_gemini_for_chunking, gemini_chunking_messages
from app.rag.embedder import embed_texts, embedding_retry_delay
from app.rag.run_logger import RagRunLog, safe_error_message
from app.rag.topics import infer_document_topic
from app.services.product_catalog_service import sync_catalog_products
from app.services.document_index_snapshot_service import capture_index_snapshot
from app.services.recommendation_catalog_service import sync_product_catalog_entry
from app.services.quota_service import (
    QuotaExceededError, check_quota, prime_quota, release_quota, reserve_ai_budget, reserve_quota,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def embed_chunks_or_fallback(
    chunk_contents: list[str],
    *,
    on_error=None,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[list[list[float] | None], bool]:
    """Embed chunks when possible, otherwise keep a lexical-only index.

    A temporary provider failure (for example an exhausted Gemini quota) must
    not discard an otherwise valid document.  ``retriever._retrieve_lexical``
    intentionally supports chunks with ``NULL`` embeddings, so callers can
    still answer product/SKU questions while semantic indexing is unavailable.
    """
    try:
        if on_progress is None:
            # Keep the small one-argument seam used by integrations and tests.
            vectors = embed_texts(chunk_contents)
        else:
            vectors = embed_texts(chunk_contents, progress_callback=on_progress)
        return vectors, True
    except Exception as error:
        if on_error is not None:
            on_error(error)
        logger.warning(
            "Embedding unavailable; storing lexical-only chunks: error_type=%s",
            type(error).__name__,
        )
        return [None] * len(chunk_contents), False


def ingest_document(
    document_id: int,
    file_bytes: bytes,
    filename: str,
    db: Session,
    use_embeddings: bool = True,
    business_id: int | None = None,
    progress_callback: Callable[[int, str, int | None, int | None], None] | None = None,
    *,
    reindex_only: bool = False,
) -> bool:
    """
    Pipeline xử lý tài liệu:
    1. Load file → raw text
    2. Chunk text
    3. Embed chunks thành vectors
    4. Lưu chunks + vectors vào DB

    Được gọi từ background task. Reindex chỉ thay index/mappings, không nhập
    lại dữ liệu catalog. Trả về kết quả attempt, độc lập trạng thái phục vụ.
    """
    with RagRunLog(
        "ingestion",
        document_id=document_id,
        filename=filename,
        file_size=len(file_bytes),
    ) as run:
        doc_query = db.query(Document).filter(Document.id == document_id)
        if business_id is not None:
            doc_query = doc_query.filter(Document.business_id == business_id)
        doc = doc_query.first()
        if doc is None:
            logger.error("Document %d not found", document_id)
            run.finish("error", phase="complete", error="document_not_found")
            return False
        if doc.status in {"disabled", "superseded"}:
            run.finish("error", phase="complete", error_code="document_not_active")
            return False

        prior_chunk_count = db.query(DocumentChunk).filter_by(document_id=doc.id).count()
        # Direct service callers rebuilding an existing index are reindex-only too.
        reindex_only = reindex_only or prior_chunk_count > 0
        keep_ready = doc.status == "ready" and prior_chunk_count > 0
        old_embedding_status, old_retry_after = doc.embedding_status, doc.retry_after
        reserved_chunks = 0
        external_chunk_quota = bool(db.info.get("tenant_schema") and not db.info.get("_quota_bridge"))
        published = False
        new_retry_after = None

        def mark_failed(code: str, message: str) -> None:
            doc.status = "ready" if keep_ready else "error"
            doc.embedding_status = old_embedding_status if keep_ready else "error"
            doc.retry_after = old_retry_after if keep_ready else None
            doc.error_code = code
            doc.error_message = message

        try:
            def report(
                percent: int,
                phase: str,
                total_chunks: int | None = None,
                completed_chunks: int | None = None,
            ) -> None:
                if progress_callback is not None:
                    progress_callback(percent, phase, total_chunks, completed_chunks)

            # Cập nhật trạng thái
            if doc.business_id is not None:
                prime_quota(db, int(doc.business_id), "rag_chunks")
            if not keep_ready:
                doc.status = "processing"
                doc.embedding_status = "processing"
            doc.error_code = None
            doc.reindex_count = (doc.reindex_count or 0) + 1
            db.commit()
            report(0, "load")

            logger.info(
                "Starting ingestion for document id=%d",
                document_id,
            )

            run.update(phase="load")
            # -------------------------------------------------
            # Bước 1: Load document
            # -------------------------------------------------
            raw_text = load_document(file_bytes, filename)
            logger.info(
                "Loaded %d characters from document id=%d",
                len(raw_text),
                document_id,
            )
            report(10, "load")
            run.update(phase="chunk", characters_loaded=len(raw_text))
            # -------------------------------------------------
            # Bước 2: Chunk text
            # -------------------------------------------------
            gemini_calls = 0
            gemini_enabled = bool(doc.business_id and settings.dedicated_gemini_api_keys)

            def detect_boundaries(parts: list[str]) -> list[int] | None:
                nonlocal gemini_calls, gemini_enabled
                # ponytail: cap remote calls per document; local boundaries cover the rest.
                if not gemini_enabled or gemini_calls >= 32:
                    return None
                gemini_calls += 1
                messages = gemini_chunking_messages(parts)
                digest = hashlib.sha256(messages[-1]["content"].encode("utf-8")).hexdigest()
                try:
                    reserve_ai_budget(
                        db, int(doc.business_id), messages,
                        idempotency_key=f"rag-chunking:{doc.id}:{doc.reindex_count}:{gemini_calls}:{digest}",
                    )
                    db.commit()
                    return _parse_model_boundaries(call_gemini_for_chunking(messages), len(parts))
                except QuotaExceededError:
                    db.rollback()
                    gemini_enabled = False
                    logger.warning("Gemini chunking quota exhausted for document id=%s", doc.id)
                except Exception as error:
                    db.rollback()
                    gemini_enabled = False
                    logger.warning("Gemini chunking failed for document id=%s: error_type=%s", doc.id, type(error).__name__)
                return None

            chunks = chunk_document(
                text=raw_text,
                filename=filename,
                chunk_size=settings.RAG_CHUNK_SIZE,
                semantic_boundary_detector=detect_boundaries if gemini_enabled else None,
                source_metadata={
                    "source": filename,
                    "document_id": int(doc.id),
                    "source_content_hash": hashlib.sha256(file_bytes).hexdigest(),
                    "source_revision": int(doc.reindex_count or 0),
                    "topic": infer_document_topic(filename, raw_text),
                },
            )
            logger.info("Created %d chunks", len(chunks))
            report(20, "chunk", len(chunks), 0)

            if not chunks:
                mark_failed("empty_document", "Không tạo được chunks từ tài liệu.")
                db.commit()
                run.finish(
                    "error",
                    phase="complete",
                    error="Không tạo được chunks từ tài liệu.",
                )
                return False

            # Check the RAG chunk allowance before remote embedding.
            # A large upload on a small plan should fail fast
            # with an actionable upgrade message instead of doing expensive
            # work only to be discarded by the final quota reservation.
            if doc.business_id is not None:
                additional_chunks = max(0, len(chunks) - prior_chunk_count)
                if additional_chunks:
                    chunk_quota = check_quota(
                        db,
                        int(doc.business_id),
                        "rag_chunks",
                        requested=additional_chunks,
                    )
                    if not chunk_quota.allowed:
                        used = int(chunk_quota.used)
                        limit = int(chunk_quota.limit) if chunk_quota.limit is not None else 0
                        remaining = max(0, limit - used)
                        format_number = lambda value: f"{int(value):,}".replace(",", ".")
                        mark_failed("chunk_quota_exceeded", (
                            f"Tài liệu tạo ra {format_number(len(chunks))} đoạn, "
                            f"gói hiện tại chỉ còn {format_number(remaining)} đoạn "
                            f"(giới hạn {format_number(limit)}). Hãy nâng cấp gói dịch vụ "
                            "hoặc chia nhỏ tài liệu."
                        ))
                        db.commit()
                        run.finish("quota_exceeded", phase="complete", quota={
                            "resource": "rag_chunks",
                            "used": used,
                            "limit": limit,
                            "requested": additional_chunks,
                        })
                        logger.warning(
                            "RAG chunk quota preflight rejected business %s, document %s: %s",
                            doc.business_id,
                            doc.id,
                            doc.error_message,
                        )
                        return False

            run.update(phase="embed", chunks_found=len(chunks))
            report(20, "embed", len(chunks), 0)
            # -------------------------------------------------
            # Bước 3: Embed chunks (hoặc lưu nhanh khi auto-seed file lớn)
            # -------------------------------------------------
            chunk_contents = [contextual_embedding_text(c) for c in chunks]
            if use_embeddings:
                if doc.business_id is not None and settings.EMBEDDING_PROVIDER.strip().lower() != "local":
                    try:
                        budget = reserve_ai_budget(
                            db,
                            int(doc.business_id),
                            [{"role": "user", "content": content} for content in chunk_contents],
                            idempotency_key=f"rag-embedding:{doc.id}:{doc.reindex_count}",
                        )
                        # Persist the charge before calling the remote
                        # embedding provider; retries of the same run reuse
                        # the reservation instead of consuming quota twice.
                        db.commit()
                        run.update(estimated_ai_cost=float(budget["cost"]))
                    except QuotaExceededError as exc:
                        db.rollback()
                        mark_failed("ai_quota_exceeded", "Đã vượt quota AI của gói dịch vụ.")
                        db.commit()
                        run.finish("quota_exceeded", phase="complete", quota=exc.detail)
                        logger.warning(
                            "AI embedding quota exhausted for business %s, document %s, resource=%s",
                            doc.business_id,
                            doc.id,
                            exc.resource,
                        )
                        return False
                embedding_error = None

                def capture_embedding_error(error: Exception) -> None:
                    nonlocal embedding_error
                    embedding_error = error

                embeddings, embeddings_used = embed_chunks_or_fallback(
                    chunk_contents,
                    on_error=capture_embedding_error,
                    on_progress=lambda fraction: report(
                        20 + int(max(0.0, min(1.0, fraction)) * 55),
                        "embed",
                        len(chunks),
                        min(len(chunks), int(max(0.0, min(1.0, fraction)) * len(chunks))),
                    ),
                )
                if not embeddings_used and keep_ready:
                    # Initial uploads may fall back to lexical search; an existing
                    # serving index must survive provider failures unchanged.
                    raise embedding_error or RuntimeError("Embedding unavailable")
                if embeddings_used:
                    logger.info("Embedded %d chunks", len(embeddings))
                    new_embedding_status = "ready"
                else:
                    new_embedding_status = "lexical_only"
                    retry_delay = (
                        embedding_retry_delay(embedding_error)
                        if embedding_error is not None
                        else None
                    )
                    new_retry_after = (
                        _utcnow() + timedelta(seconds=retry_delay)
                        if retry_delay is not None
                        else None
                    )
            else:
                embeddings = [None] * len(chunks)
                embeddings_used = False
                new_embedding_status = "lexical_only"
                logger.info(
                    "Fast ingestion enabled for document id=%d: storing %d chunks without remote embeddings",
                    document_id,
                    len(chunks),
                )

            if len(embeddings) != len(chunks):
                raise ValueError(
                    "Số lượng embeddings không khớp số chunks: "
                    f"{len(embeddings)} != {len(chunks)}."
                )

            run.update(phase="store", embeddings_skipped=not embeddings_used)
            report(75, "store", len(chunks), 0)
            # -------------------------------------------------
            # Bước 4: Replace the previous index atomically.
            # -------------------------------------------------
            # Re-processing a document must not append duplicate chunks.
            # This delete happens in the same transaction as the inserts, so
            # a failed embedding/store rolls back and leaves the old index
            # available for inspection.
            if doc.business_id is not None:
                delta = len(chunks) - prior_chunk_count
                if delta > 0:
                    reserve_quota(db, int(doc.business_id), "rag_chunks", requested=delta)
                    reserved_chunks = delta
            if prior_chunk_count and doc.business_id is not None:
                capture_index_snapshot(db, doc, reason="pre_publish")
            # Explicit cleanup also works on SQLite fixtures without FK cascades.
            old_ids = select(DocumentChunk.id).where(DocumentChunk.document_id == doc.id)
            db.query(RecommendationCatalogChunkMapping).filter(
                RecommendationCatalogChunkMapping.document_chunk_id.in_(old_ids),
            ).delete(synchronize_session=False)
            db.query(DocumentChunk).filter(
                DocumentChunk.document_id == document_id,
            ).delete(synchronize_session=False)

            for chunk, embedding in zip(chunks, embeddings):
                db_chunk = DocumentChunk(
                    document_id=document_id,
                    content=chunk.content,
                    chunk_index=chunk.index,
                    embedding=embedding,
                    metadata_=chunk.metadata,
                )
                db.add(db_chunk)

            doc.status = "ready"
            doc.embedding_status = new_embedding_status
            doc.retry_after = new_retry_after
            doc.chunk_count = len(chunks)
            doc.processed_at = _utcnow()
            doc.error_message = None
            doc.error_code = None
            if doc.embedding_status == "ready":
                doc.retry_after = None
            # Keep catalogue projections and the index in one transaction.
            # A failed quota check or embedding must not publish products
            # from a document that cannot be searched.
            if doc.business_id is not None:
                synced_products = []
                if not reindex_only:
                    synced_products = sync_catalog_products(
                        db,
                        business_id=doc.business_id,
                        source_document_id=doc.id,
                        text=raw_text,
                    )
                db.flush()
                stored_chunks = db.query(DocumentChunk).filter(
                    DocumentChunk.document_id == doc.id,
                ).all()
                catalog_products = db.query(Product).filter(
                    Product.business_id == doc.business_id,
                ).order_by(Product.id).populate_existing().with_for_update().all()
                mapped_products = 0
                import re
                for product in catalog_products:
                    sku = str(product.sku or "").strip()
                    if not sku:
                        continue
                    sku_pattern = re.compile(rf"(?<![\w-]){re.escape(sku)}(?![\w-])", re.IGNORECASE)
                    mapped_chunk_ids = [
                        chunk.id for chunk in stored_chunks
                        if sku_pattern.search(chunk.content or "")
                    ]
                    if not mapped_chunk_ids:
                        continue
                    # The shared sync replaces all links for an entry. Retain
                    # evidence belonging to other documents in this same shop.
                    other_chunk_ids = db.scalars(
                        select(RecommendationCatalogChunkMapping.document_chunk_id)
                        .join(RecommendationCatalogEntry)
                        .join(DocumentChunk, DocumentChunk.id == RecommendationCatalogChunkMapping.document_chunk_id)
                        .join(Document, Document.id == DocumentChunk.document_id)
                        .where(
                            RecommendationCatalogEntry.business_id == doc.business_id,
                            RecommendationCatalogEntry.object_type == "product",
                            RecommendationCatalogEntry.external_id == str(product.id),
                            Document.business_id == doc.business_id,
                            Document.id != doc.id,
                        )
                    ).all()
                    sync_product_catalog_entry(
                        db,
                        product,
                        source="knowledge_document",
                        document_chunk_ids=[*other_chunk_ids, *mapped_chunk_ids],
                    )
                    mapped_products += 1
                logger.info(
                    "Synchronized %d structured products and rebuilt %d exact-SKU catalog mappings from document id=%d",
                    len(synced_products),
                    mapped_products,
                    document_id,
                )
            # Legacy single-DB quotas share this transaction. Tenant-schema
            # quotas use the existing control-plane bridge and are compensated
            # below if publishing fails.
            if doc.business_id is not None and len(chunks) < prior_chunk_count and not external_chunk_quota:
                release_quota(db, int(doc.business_id), "rag_chunks", prior_chunk_count - len(chunks))
            db.commit()
            published = True
            if doc.business_id is not None and len(chunks) < prior_chunk_count and external_chunk_quota:
                release_quota(db, int(doc.business_id), "rag_chunks", prior_chunk_count - len(chunks))
            report(100, "complete", len(chunks), len(chunks))

            logger.info(
                "Ingestion complete: document id=%d → %d chunks stored",
                document_id,
                len(chunks),
            )
            run.finish("success", phase="complete", chunks_stored=len(chunks))
            return True

        except Exception as e:
            logger.warning(
                "Ingestion failed for document %d: error_type=%s",
                document_id,
                type(e).__name__,
            )
            db.rollback()
            failed_query = db.query(Document).filter(Document.id == document_id)
            if business_id is not None:
                failed_query = failed_query.filter(Document.business_id == business_id)
            failed_doc = failed_query.first()
            if published:
                # An observability/progress error after commit cannot unpublish
                # the successfully stored index or refund its capacity.
                logger.exception("Post-publish RAG bookkeeping failed for document %d", document_id)
                return True
            if reserved_chunks and external_chunk_quota:
                # The existing quota bridge commits on the platform connection.
                release_quota(db, int(doc.business_id), "rag_chunks", reserved_chunks)
            code = (
                "chunk_quota_exceeded" if isinstance(e, QuotaExceededError)
                else e.code if isinstance(e, DocumentValidationError)
                else "document_processing_failed"
            )
            if failed_doc is not None:
                mark_failed(code, (
                    "Đã vượt quota chunks RAG của gói dịch vụ." if isinstance(e, QuotaExceededError)
                    else safe_error_message(e) if isinstance(e, DocumentValidationError)
                    else "Không thể xử lý tài liệu; vui lòng thử lại hoặc liên hệ quản trị viên."
                ))
                db.commit()
            run.finish("error", phase="complete", error_type=type(e).__name__, error_code=code)
            return False


def delete_document(document_id: int, db: Session, business_id: int | None = None) -> bool:
    """Xóa document và tất cả chunks liên quan."""
    doc_query = db.query(Document).filter(Document.id == document_id)
    if business_id is not None:
        doc_query = doc_query.filter(Document.business_id == business_id)
    doc = doc_query.first()
    if doc is None:
        return False

    db.delete(doc)
    return True
