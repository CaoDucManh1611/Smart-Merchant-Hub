"""
Document Management API – upload, list, delete tài liệu.
"""

import logging
import re
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.models.document import Document, DocumentChunk
from app.models.rag_run import RagRun
from app.rag.loader import detect_file_type, LOADERS
from app.schemas.rag import DocumentChunkOut, DocumentListOut, DocumentOut
from app.services.ingestion_service import (
    delete_document,
    ingest_document,
)
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.auth.dependencies import require_write_access
from app.services.job_service import dispatch_due_jobs, enqueue_job
from app.services.quota_service import QuotaExceededError, prime_quota, release_quota, reserve_quota

logger = logging.getLogger(__name__)

_SENSITIVE_ERROR = re.compile(
    r"(?i)(token|secret|authorization|api[_-]?key)\s*[=:]\s*[^\s,;]+"
)


def _safe_error(exc: Exception) -> str:
    """Keep provider credentials out of persisted RAG diagnostics."""
    message = _SENSITIVE_ERROR.sub(r"\1=[redacted]", str(exc or ""))
    return message[:500] or "RAG ingestion failed"

router = APIRouter()


def _queue_ingestion(db: Session, doc: Document, *, kind: str) -> RagRun:
    run = RagRun(
        business_id=doc.business_id,
        document_id=doc.id,
        kind=kind,
        status="queued",
        source_document_ids=[doc.id],
    )
    db.add(run)
    db.flush()
    enqueue_job(
        db,
        business_id=doc.business_id,
        kind="rag.ingest",
        payload={"run_id": run.id, "document_id": doc.id},
        idempotency_key=f"rag:{kind}:{run.id}",
    )
    return run


def _run_out(row: RagRun) -> dict:
    return {
        "id": row.id,
        "document_id": row.document_id,
        "kind": row.kind,
        "status": row.status,
        "phase": row.phase,
        "chunk_count": row.chunk_count,
        "attempts": row.attempts,
        "error_message": row.error_message,
        "created_at": row.created_at,
        "completed_at": row.completed_at,
    }


def _dispatch_rag_job(db: Session, payload: dict, business_id: int) -> None:
    run = db.query(RagRun).filter(RagRun.id == int(payload["run_id"]), RagRun.business_id == business_id).first()
    doc = db.query(Document).filter(Document.id == int(payload["document_id"]), Document.business_id == business_id).first()
    if run is None or doc is None:
        return
    prior_chunk_count = int(doc.chunk_count or 0)
    # Seed the current total before ingestion replaces chunks.  This keeps a
    # reindex from counting the old chunks twice and leaves a safe baseline if
    # the provider fails before producing a new index.
    prime_quota(db, business_id, "rag_chunks")
    db.commit()
    run.status = "processing"
    run.phase = "load"
    run.attempts = (run.attempts or 0) + 1
    db.commit()
    try:
        ingest_document(doc.id, bytes(doc.source_bytes or b""), doc.filename, db, business_id=business_id)
    except Exception as exc:
        run.status = "failed"
        run.phase = "complete"
        run.error_message = _safe_error(exc)
        run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
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
                requested=prior_chunk_count - int(doc.chunk_count or 0),
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
                run.error_message = doc.error_message
                run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
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
    run.error_message = doc.error_message
    run.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()


# =========================================================
# UPLOAD
# =========================================================


@router.post(
    "/upload",
    response_model=DocumentOut,
    status_code=201,
    dependencies=[Depends(require_write_access)],
)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    """
    Upload tài liệu cho RAG knowledge base.

    Hỗ trợ: PDF, DOCX, TXT, CSV, Markdown, HTML.
    File sẽ được xử lý (chunk + embed) trong background.
    """
    if not file.filename:
        raise HTTPException(400, "Tên file không hợp lệ.")

    file_type = detect_file_type(file.filename)
    if file_type not in LOADERS:
        supported = ", ".join(sorted(LOADERS.keys()))
        raise HTTPException(
            400,
            f"Không hỗ trợ file '.{file_type}'. "
            f"Các loại hỗ trợ: {supported}",
        )

    # Đọc file bytes
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "File rỗng.")

    # Giới hạn kích thước (20MB)
    max_size = 20 * 1024 * 1024
    if len(file_bytes) > max_size:
        raise HTTPException(
            400,
            f"File quá lớn. Giới hạn: {max_size // (1024*1024)}MB",
        )

    # Only consume the document slot after cheap validation succeeds; an
    # oversized upload must not leave a phantom quota reservation behind.
    try:
        reserve_quota(db, tenant.business_id, "documents")
    except QuotaExceededError as exc:
        raise HTTPException(status_code=429, detail=exc.detail) from exc

    # Tạo record Document
    doc = Document(
        business_id=tenant.business_id,
        filename=file.filename,
        file_type=file_type,
        file_size=len(file_bytes),
        status="pending",
        source_bytes=file_bytes,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    _queue_ingestion(db, doc, kind="ingestion")
    db.commit()

    logger.info(
        "Document uploaded: %s (id=%d), processing in background",
        file.filename,
        doc.id,
    )

    return doc


@router.post("/{document_id}/reindex", response_model=DocumentOut, dependencies=[Depends(require_write_access)])
async def reindex_document(
    document_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    """Rebuild chunks/embeddings from the retained source file."""
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.business_id == tenant.business_id,
    ).first()
    if doc is None:
        raise HTTPException(404, "Tài liệu không tồn tại.")
    if not doc.source_bytes:
        raise HTTPException(409, "Tài liệu cũ không có bản gốc để reindex; hãy upload lại.")
    source = bytes(doc.source_bytes)
    doc.status = "pending"
    doc.embedding_status = "pending"
    doc.error_message = None
    db.commit()
    _queue_ingestion(db, doc, kind="reindex")
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/{document_id}/runs")
async def list_document_runs(document_id: int, db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    if db.query(Document.id).filter(Document.id == document_id, Document.business_id == tenant.business_id).first() is None:
        raise HTTPException(404, "Tài liệu không tồn tại.")
    runs = db.query(RagRun).filter(RagRun.document_id == document_id, RagRun.business_id == tenant.business_id).order_by(RagRun.id.desc()).limit(100).all()
    return {"items": [_run_out(row) for row in runs], "total": len(runs)}


@router.post("/runs/{run_id}/retry", status_code=201, dependencies=[Depends(require_write_access)])
async def retry_failed_run(
    run_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    """Queue a new durable run for one failed ingestion without mutating history."""
    previous = db.query(RagRun).filter(
        RagRun.id == run_id,
        RagRun.business_id == tenant.business_id,
    ).first()
    if previous is None:
        raise HTTPException(404, "RAG run không tồn tại.")
    if previous.status != "failed":
        raise HTTPException(409, "Chỉ có thể thử lại RAG run đã lỗi.")
    doc = db.query(Document).filter(
        Document.id == previous.document_id,
        Document.business_id == tenant.business_id,
    ).first()
    if doc is None or not doc.source_bytes:
        raise HTTPException(409, "Tài liệu không còn bản gốc để thử lại; hãy upload lại.")
    doc.status = "pending"
    doc.embedding_status = "pending"
    doc.error_message = None
    run = _queue_ingestion(db, doc, kind="retry")
    db.commit()
    db.refresh(run)
    return _run_out(run)


@router.post("/jobs/dispatch")
async def dispatch_document_jobs(db: Session = Depends(get_db), tenant: TenantContext = Depends(get_tenant_context)):
    processed = dispatch_due_jobs(
        db,
        business_id=tenant.business_id,
        handlers={"rag.ingest": lambda payload: _dispatch_rag_job(db, payload, tenant.business_id)},
        kinds={"rag.ingest"},
    )
    return {"processed": processed}


# =========================================================
# LIST
# =========================================================


@router.get("", response_model=DocumentListOut)
async def list_documents(
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    """Danh sách tất cả tài liệu đã upload."""
    docs = (
        db.query(Document)
        .filter(Document.business_id == tenant.business_id)
        .order_by(Document.uploaded_at.desc())
        .all()
    )
    return DocumentListOut(
        documents=[DocumentOut.model_validate(d) for d in docs],
        total=len(docs),
    )


# =========================================================
# GET ONE
# =========================================================


@router.get(
    "/{document_id}",
    response_model=DocumentOut,
)
async def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    """Xem chi tiết 1 tài liệu."""
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.business_id == tenant.business_id,
    ).first()
    if doc is None:
        raise HTTPException(404, "Tài liệu không tồn tại.")
    return doc


@router.get(
    "/{document_id}/chunks",
    response_model=list[DocumentChunkOut],
)
async def list_document_chunks(
    document_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    """Xem các chunks đã tạo và trạng thái embedding của một tài liệu."""
    if db.query(Document).filter(
        Document.id == document_id,
        Document.business_id == tenant.business_id,
    ).first() is None:
        raise HTTPException(404, "Tài liệu không tồn tại.")

    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .limit(500)
        .all()
    )

    return [
        DocumentChunkOut(
            id=chunk.id,
            document_id=chunk.document_id,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            metadata=chunk.metadata_,
            has_embedding=chunk.embedding is not None,
        )
        for chunk in chunks
    ]


# =========================================================
# DELETE
# =========================================================


@router.delete("/{document_id}", status_code=204, dependencies=[Depends(require_write_access)])
async def remove_document(
    document_id: int,
    db: Session = Depends(get_db),
    tenant: TenantContext = Depends(get_tenant_context),
):
    """Xóa tài liệu và tất cả chunks liên quan."""
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.business_id == tenant.business_id,
    ).first()
    prior_chunks = int(doc.chunk_count or 0) if doc else 0
    deleted = delete_document(document_id, db, business_id=tenant.business_id)
    if not deleted:
        raise HTTPException(404, "Tài liệu không tồn tại.")
    release_quota(db, tenant.business_id, "documents")
    if prior_chunks:
        release_quota(db, tenant.business_id, "rag_chunks", prior_chunks)
    db.commit()
    return None
