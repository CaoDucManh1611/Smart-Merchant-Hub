"""Versioned, tenant-scoped rollback for published document indexes."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document, DocumentChunk, DocumentIndexSnapshot
from app.models.recommendation_catalog import (
    RecommendationCatalogChunkMapping,
    RecommendationCatalogEntry,
)
from app.services.quota_service import release_quota, reserve_quota


logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def capture_index_snapshot(
    db: Session,
    document: Document,
    *,
    reason: str = "pre_publish",
    prune: bool = True,
) -> DocumentIndexSnapshot | None:
    """Capture chunks and their catalog links inside the caller transaction."""
    chunks = db.scalars(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document.id)
        .order_by(DocumentChunk.chunk_index, DocumentChunk.id)
    ).all()
    if not chunks:
        return None
    chunk_ids = [chunk.id for chunk in chunks]
    mapping_rows = db.execute(
        select(
            RecommendationCatalogChunkMapping.document_chunk_id,
            RecommendationCatalogChunkMapping.catalog_entry_id,
            RecommendationCatalogChunkMapping.mapping_type,
        ).where(RecommendationCatalogChunkMapping.document_chunk_id.in_(chunk_ids))
    ).all()
    mappings: dict[int, list[dict]] = {}
    for chunk_id, entry_id, mapping_type in mapping_rows:
        mappings.setdefault(int(chunk_id), []).append(
            {"catalog_entry_id": int(entry_id), "mapping_type": str(mapping_type)}
        )
    version = int(db.scalar(
        select(func.max(DocumentIndexSnapshot.version)).where(
            DocumentIndexSnapshot.document_id == document.id,
        )
    ) or 0) + 1
    snapshot = DocumentIndexSnapshot(
        document_id=document.id,
        business_id=int(document.business_id),
        version=version,
        reason=reason,
        document_state={
            "status": document.status,
            "embedding_status": document.embedding_status,
            "retry_after": _iso(document.retry_after),
            "processed_at": _iso(document.processed_at),
            "chunk_count": len(chunks),
        },
        chunks_payload=[
            {
                "content": chunk.content,
                "chunk_index": int(chunk.chunk_index),
                "embedding": None if chunk.embedding is None else [float(value) for value in chunk.embedding],
                "metadata": chunk.metadata_,
                "mappings": mappings.get(int(chunk.id), []),
            }
            for chunk in chunks
        ],
    )
    db.add(snapshot)
    db.flush()
    if prune:
        retention = max(1, int(settings.RAG_INDEX_SNAPSHOT_RETENTION))
        stale = db.scalars(
            select(DocumentIndexSnapshot)
            .where(DocumentIndexSnapshot.document_id == document.id)
            .order_by(DocumentIndexSnapshot.version.desc())
            .offset(retention)
        ).all()
        for row in stale:
            db.delete(row)
    return snapshot


def restore_index_snapshot(
    db: Session,
    *,
    business_id: int,
    document_id: int,
    snapshot_id: int,
) -> DocumentIndexSnapshot:
    """Restore one snapshot atomically and preserve the displaced index."""
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.business_id == business_id,
        ).with_for_update()
    )
    snapshot = db.scalar(
        select(DocumentIndexSnapshot).where(
            DocumentIndexSnapshot.id == snapshot_id,
            DocumentIndexSnapshot.document_id == document_id,
            DocumentIndexSnapshot.business_id == business_id,
        )
    )
    if document is None or snapshot is None:
        raise ValueError("snapshot_not_found_for_tenant_document")
    payload = list(snapshot.chunks_payload or [])
    if not payload:
        raise ValueError("snapshot_has_no_chunks")
    referenced_entry_ids = {
        int(mapping["catalog_entry_id"])
        for chunk in payload
        for mapping in chunk.get("mappings", [])
    }
    if referenced_entry_ids:
        valid_entry_ids = set(db.scalars(
            select(RecommendationCatalogEntry.id).where(
                RecommendationCatalogEntry.id.in_(referenced_entry_ids),
                RecommendationCatalogEntry.business_id == business_id,
            )
        ).all())
        if valid_entry_ids != referenced_entry_ids:
            raise ValueError("snapshot_catalog_mapping_is_stale_or_cross_tenant")

    current_count = int(db.scalar(
        select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == document_id)
    ) or 0)
    target_count = len(payload)
    delta = target_count - current_count
    external_quota = bool(db.info.get("tenant_schema") and not db.info.get("_quota_bridge"))
    reserved = 0
    published = False
    try:
        if delta > 0:
            reserve_quota(db, business_id, "rag_chunks", requested=delta)
            reserved = delta
        capture_index_snapshot(db, document, reason="pre_rollback", prune=False)
        current_ids = select(DocumentChunk.id).where(DocumentChunk.document_id == document_id)
        db.query(RecommendationCatalogChunkMapping).filter(
            RecommendationCatalogChunkMapping.document_chunk_id.in_(current_ids),
        ).delete(synchronize_session=False)
        db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete(
            synchronize_session=False,
        )
        for stored in payload:
            chunk = DocumentChunk(
                document_id=document_id,
                content=stored["content"],
                chunk_index=int(stored["chunk_index"]),
                embedding=stored.get("embedding"),
                metadata_=stored.get("metadata"),
            )
            db.add(chunk)
            db.flush()
            for mapping in stored.get("mappings", []):
                db.add(RecommendationCatalogChunkMapping(
                    catalog_entry_id=int(mapping["catalog_entry_id"]),
                    document_chunk_id=chunk.id,
                    mapping_type=str(mapping.get("mapping_type") or "primary"),
                ))
        state = snapshot.document_state or {}
        document.status = str(state.get("status") or "ready")
        document.embedding_status = str(state.get("embedding_status") or "ready")
        document.retry_after = _datetime(state.get("retry_after"))
        document.processed_at = _datetime(state.get("processed_at"))
        document.chunk_count = target_count
        document.error_code = None
        document.error_message = None
        snapshot.restored_at = _utcnow()
        if delta < 0 and not external_quota:
            # Keep local quota and restored chunks in the same transaction.
            release_quota(db, business_id, "rag_chunks", -delta)
        db.commit()
        published = True
        if delta < 0 and external_quota:
            release_quota(db, business_id, "rag_chunks", -delta)
        return snapshot
    except Exception:
        if published:
            # The index is already durable. Do not report the restore as failed
            # merely because cross-database quota reconciliation failed.
            logger.exception(
                "Index snapshot restored but external quota reconciliation failed",
                extra={
                    "business_id": business_id,
                    "document_id": document_id,
                    "snapshot_id": snapshot_id,
                    "quota_delta": delta,
                },
            )
            return snapshot
        db.rollback()
        if reserved and external_quota:
            release_quota(db, business_id, "rag_chunks", reserved)
        raise
