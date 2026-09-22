"""Durable background jobs for knowledge-base ingestion.

The HTTP API only creates the document and queue row.  This module is used by
the worker (and by the legacy manual dispatch endpoint) so a slow embedding
provider never owns an API request.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.document import Document, DocumentChunk
from app.models.rag_run import RagRun
from app.rag.run_logger import safe_error_message
from app.services.ingestion_service import ingest_document
from app.services.quota_service import QuotaExceededError, prime_quota, release_quota, reserve_quota

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _safe_error(exc: Exception) -> str:
    """Keep provider credentials out of persisted RAG diagnostics."""
    return safe_error_message(exc)


def dispatch_rag_job(
    db: Session,
    payload: dict[str, Any],
    business_id: int,
    *,
    ingest_fn: Callable[..., None] = ingest_document,
) -> None:
    """Process one queued RAG run and persist durable progress.

    ``ingest_fn`` is injectable so the compatibility API endpoint can keep its
    existing unit-test seam while the real worker uses the service directly.
    """
    run = db.query(RagRun).filter(
        RagRun.id == int(payload["run_id"]),
        RagRun.business_id == business_id,
    ).first()
    doc = db.query(Document).filter(
        Document.id == int(payload["document_id"]),
        Document.business_id == business_id,
    ).first()
    if run is None or doc is None:
        return

    prior_chunk_count = int(doc.chunk_count or 0)
    # Seed the current total before ingestion replaces chunks. This keeps a
    # reindex from counting the old chunks twice.
    prime_quota(db, business_id, "rag_chunks")
    run.status = "processing"
    run.phase = "load"
    run.attempts = (run.attempts or 0) + 1
    run.total_chunks = 0
    run.completed_chunks = 0
    run.progress_percent = 0
    run.error_message = None
    db.commit()

    def report_progress(
        percent: int,
        phase: str,
        total_chunks: int | None = None,
        completed_chunks: int | None = None,
    ) -> None:
        """Persist a small, bounded progress update for UI polling."""
        current = db.get(RagRun, run.id)
        if current is None:
            return
        requested_percent = max(0, min(100, int(percent)))
        if requested_percent >= int(current.progress_percent or 0):
            current.phase = phase
        current.progress_percent = max(int(current.progress_percent or 0), requested_percent)
        if total_chunks is not None:
            current.total_chunks = max(int(current.total_chunks or 0), int(total_chunks), 0)
        if completed_chunks is not None:
            current.completed_chunks = max(int(current.completed_chunks or 0), int(completed_chunks), 0)
        db.commit()

    try:
        ingest_fn(
            doc.id,
            bytes(doc.source_bytes or b""),
            doc.filename,
            db,
            business_id=business_id,
            progress_callback=report_progress,
        )
    except Exception as exc:
        # Keep the run visible as failed, then re-raise so the durable queue can
        # apply its bounded retry/backoff policy.
        db.rollback()
        failed = db.get(RagRun, run.id)
        if failed is not None:
            failed.status = "failed"
            failed.phase = "complete"
            failed.error_message = _safe_error(exc)
            failed.completed_at = _utcnow()
            db.commit()
        raise

    db.refresh(doc)
    db.refresh(run)
    if doc.status == "ready":
        delta_chunks = max(0, int(doc.chunk_count or 0) - prior_chunk_count)
        if int(doc.chunk_count or 0) < prior_chunk_count:
            release_quota(
                db,
                business_id,
                "rag_chunks",
                amount=prior_chunk_count - int(doc.chunk_count or 0),
            )
        if delta_chunks:
            try:
                reserve_quota(
                    db,
                    business_id,
                    "rag_chunks",
                    requested=delta_chunks,
                    idempotency_key=f"rag-run:{run.id}",
                )
            except QuotaExceededError as exc:
                db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete(synchronize_session=False)
                doc.status = "error"
                doc.embedding_status = "error"
                doc.chunk_count = 0
                doc.error_message = "Đã vượt quota chunks RAG của gói dịch vụ."
                if prior_chunk_count:
                    release_quota(db, business_id, "rag_chunks", prior_chunk_count)
                run.status = "failed"
                run.phase = "complete"
                run.chunk_count = 0
                run.completed_chunks = 0
                run.progress_percent = 100
                run.error_message = doc.error_message
                run.completed_at = _utcnow()
                db.commit()
                logger.warning(
                    "RAG chunk quota exhausted for business %d, document %d: %s",
                    business_id,
                    doc.id,
                    exc.detail,
                )
                return

    run.status = "completed" if doc.status == "ready" else "failed"
    run.phase = "complete"
    run.chunk_count = int(doc.chunk_count or 0)
    run.total_chunks = max(int(run.total_chunks or 0), int(doc.chunk_count or 0))
    run.completed_chunks = int(doc.chunk_count or 0) if doc.status == "ready" else int(run.completed_chunks or 0)
    # A terminal rejection (for example a package quota limit) is also a
    # completed background attempt; the UI can show the persisted error next
    # to the 100% terminal progress instead of looking stuck.
    run.progress_percent = 100 if doc.status in {"ready", "error"} else int(run.progress_percent or 0)
    run.error_message = doc.error_message
    run.completed_at = _utcnow()
    db.commit()
