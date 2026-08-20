"""
Ingestion Service – orchestrate pipeline: Load → Chunk → Embed → Store.

Chạy như background task để không block request.
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document, DocumentChunk
from app.rag.loader import load_document, detect_file_type
from app.rag.chunker import chunk_text
from app.rag.embedder import embed_texts
from app.rag.run_logger import RagRunLog

logger = logging.getLogger(__name__)


def ingest_document(
    document_id: int,
    file_bytes: bytes,
    filename: str,
    db: Session,
    use_embeddings: bool = True,
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
        doc = db.get(Document, document_id)
        if doc is None:
            logger.error("Document %d not found", document_id)
            run.finish("error", phase="complete", error="document_not_found")
            return

        try:
            # Cập nhật trạng thái
            doc.status = "processing"
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
                embeddings = embed_texts(chunk_contents)
                logger.info("Embedded %d chunks", len(embeddings))
            else:
                embeddings = [None] * len(chunks)
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

            run.update(phase="store", embeddings_skipped=not use_embeddings)
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
            doc.processed_at = datetime.utcnow()
            doc.error_message = None
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
                db.commit()
            run.finish(
                "error",
                phase="complete",
                error_type=type(e).__name__,
                error=str(e)[:1000],
            )


def delete_document(document_id: int, db: Session) -> bool:
    """Xóa document và tất cả chunks liên quan."""
    doc = db.get(Document, document_id)
    if doc is None:
        return False

    db.delete(doc)
    db.commit()
    logger.info("Deleted document %d", document_id)
    return True
