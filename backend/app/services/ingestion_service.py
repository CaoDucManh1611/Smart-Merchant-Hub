"""
Ingestion Service – orchestrate pipeline: Load → Chunk → Embed → Store.

Chạy như background task để không block request.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document, DocumentChunk
from app.rag.loader import load_document, detect_file_type
from app.rag.chunker import chunk_text
from app.rag.embedder import embed_texts, embedding_retry_delay
from app.rag.run_logger import RagRunLog

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def embed_chunks_or_fallback(
    chunk_contents: list[str],
    *,
    on_error=None,
) -> tuple[list[list[float] | None], bool]:
    """Embed chunks when possible, otherwise keep a lexical-only index.

    A temporary provider failure (for example an exhausted Gemini quota) must
    not discard an otherwise valid document.  ``retriever._retrieve_lexical``
    intentionally supports chunks with ``NULL`` embeddings, so callers can
    still answer product/SKU questions while semantic indexing is unavailable.
    """
    try:
        return embed_texts(chunk_contents), True
    except Exception as error:
        if on_error is not None:
            on_error(error)
        logger.warning(
            "Embedding unavailable; storing lexical-only chunks: %s",
            error,
        )
        return [None] * len(chunk_contents), False


def ingest_document(
    document_id: int,
    file_bytes: bytes,
    filename: str,
    db: Session,
    use_embeddings: bool = True,
    business_id: int | None = None,
) -> None:
    """
    Pipeline xử lý tài liệu:
    1. Load file → raw text
    2. Chunk text
    3. Embed chunks thành vectors
    4. Lưu chunks + vectors vào DB

    Được gọi từ background task.
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
            return

        try:
            # Cập nhật trạng thái
            doc.status = "processing"
            doc.embedding_status = "processing"
            doc.reindex_count = (doc.reindex_count or 0) + 1
            db.commit()

            logger.info(
                "Starting ingestion for: %s (id=%d)",
                filename,
                document_id,
            )

            run.update(phase="load")
            # -------------------------------------------------
            # Bước 1: Load document
            # -------------------------------------------------
            raw_text = load_document(file_bytes, filename)
            logger.info(
                "Loaded %d characters from %s",
                len(raw_text),
                filename,
            )

            run.update(phase="chunk", characters_loaded=len(raw_text))
            # -------------------------------------------------
            # Bước 2: Chunk text
            # -------------------------------------------------
            chunks = chunk_text(
                text=raw_text,
                chunk_size=settings.RAG_CHUNK_SIZE,
                chunk_overlap=settings.RAG_CHUNK_OVERLAP,
                source_metadata={"source": filename},
            )
            logger.info("Created %d chunks", len(chunks))

            if not chunks:
                doc.status = "error"
                doc.embedding_status = "error"
                doc.error_message = "Không tạo được chunks từ tài liệu."
                db.commit()
                run.finish(
                    "error",
                    phase="complete",
                    error="Không tạo được chunks từ tài liệu.",
                )
                return

            run.update(phase="embed", chunks_found=len(chunks))
            # -------------------------------------------------
            # Bước 3: Embed chunks (hoặc lưu nhanh khi auto-seed file lớn)
            # -------------------------------------------------
            chunk_contents = [c.content for c in chunks]
            if use_embeddings:
                embedding_error = None

                def capture_embedding_error(error: Exception) -> None:
                    nonlocal embedding_error
                    embedding_error = error

                embeddings, embeddings_used = embed_chunks_or_fallback(
                    chunk_contents,
                    on_error=capture_embedding_error,
                )
                if embeddings_used:
                    logger.info("Embedded %d chunks", len(embeddings))
                    doc.embedding_status = "ready"
                else:
                    doc.embedding_status = "lexical_only"
                    retry_delay = (
                        embedding_retry_delay(embedding_error)
                        if embedding_error is not None
                        else None
                    )
                    doc.retry_after = (
                        _utcnow() + timedelta(seconds=retry_delay)
                        if retry_delay is not None
                        else None
                    )
            else:
                embeddings = [None] * len(chunks)
                embeddings_used = False
                doc.embedding_status = "lexical_only"
                logger.info(
                    "Fast ingestion enabled for %s: storing %d chunks without remote embeddings",
                    filename,
                    len(chunks),
                )

            if len(embeddings) != len(chunks):
                raise ValueError(
                    "Số lượng embeddings không khớp số chunks: "
                    f"{len(embeddings)} != {len(chunks)}."
                )

            run.update(phase="store", embeddings_skipped=not embeddings_used)
            # -------------------------------------------------
            # Bước 4: Replace the previous index atomically.
            # -------------------------------------------------
            # Re-processing a document must not append duplicate chunks.
            # This delete happens in the same transaction as the inserts, so
            # a failed embedding/store rolls back and leaves the old index
            # available for inspection.
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
            doc.chunk_count = len(chunks)
            doc.processed_at = _utcnow()
            doc.error_message = None
            doc.retry_after = None
            db.commit()

            logger.info(
                "Ingestion complete: %s → %d chunks stored",
                filename,
                len(chunks),
            )
            run.finish("success", phase="complete", chunks_stored=len(chunks))

        except Exception as e:
            logger.exception(
                "Ingestion failed for document %d: %s",
                document_id,
                str(e),
            )
            db.rollback()
            failed_doc = db.get(Document, document_id)
            if failed_doc is not None:
                failed_doc.status = "error"
                failed_doc.error_message = str(e)[:500]
                failed_doc.embedding_status = "error"
                db.commit()
            run.finish(
                "error",
                phase="complete",
                error_type=type(e).__name__,
                error=str(e)[:1000],
            )


def delete_document(document_id: int, db: Session, business_id: int | None = None) -> bool:
    """Xóa document và tất cả chunks liên quan."""
    doc_query = db.query(Document).filter(Document.id == document_id)
    if business_id is not None:
        doc_query = doc_query.filter(Document.business_id == business_id)
    doc = doc_query.first()
    if doc is None:
        return False

    db.delete(doc)
    db.commit()
    logger.info("Deleted document %d", document_id)
    return True
