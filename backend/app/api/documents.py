"""
Document Management API – upload, list, delete tài liệu.
"""

import logging

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from sqlalchemy.orm import Session

from app.tenancy.crm_session import get_tenant_db
from app.models.document import Document, DocumentChunk
from app.models.crm_job import CrmJob
from app.models.rag_run import RagRun
from app.rag.loader import detect_file_type, LOADERS
from app.schemas.rag import DocumentChunkOut, DocumentListOut, DocumentOut, RagRunListOut, RagRunOut
from app.services.ingestion_service import (
    delete_document,
    ingest_document,
)
from app.services.rag_job_service import dispatch_rag_job
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.auth.dependencies import require_write_access
from app.services.job_service import dispatch_due_jobs, enqueue_job
from app.services.quota_service import QuotaExceededError, release_quota, reserve_quota

logger = logging.getLogger(__name__)

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
        max_attempts=5,
    )
    return run


def _has_active_ingestion(db: Session, *, business_id: int, document_id: int) -> bool:
    active_run = db.query(RagRun.id).filter(
        RagRun.business_id == business_id,
        RagRun.document_id == document_id,
        RagRun.status.in_(("queued", "processing")),
    ).first()
    if active_run is not None:
        return True
    active_job = db.query(CrmJob.id).filter(
        CrmJob.business_id == business_id,
        CrmJob.kind == "rag.ingest",
        CrmJob.status.in_(("pending", "running")),
        CrmJob.payload["document_id"].as_integer() == document_id,
    ).first()
    return active_job is not None


def _run_out(row: RagRun) -> dict:
    return {
        "id": row.id,
        "document_id": row.document_id,
        "kind": row.kind,
        "status": row.status,
        "phase": row.phase,
        "chunk_count": row.chunk_count,
        "total_chunks": row.total_chunks,
        "completed_chunks": row.completed_chunks,
        "progress_percent": row.progress_percent,
        "attempts": row.attempts,
        "error_message": row.error_message,
        "created_at": row.created_at,
        "completed_at": row.completed_at,
    }


def _dispatch_rag_job(db: Session, payload: dict, business_id: int) -> None:
    # Kept as a compatibility seam for the manual dispatch endpoint and
    # existing integrations. Production uses the dedicated worker directly.
    dispatch_rag_job(db, payload, business_id, ingest_fn=ingest_document)


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
    db: Session = Depends(get_tenant_db),
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

    try:
        # Persist the source, run and queue row as one tenant transaction. The
        # HTTP request never performs chunking or calls an embedding provider.
        doc = Document(
            business_id=tenant.business_id,
            filename=file.filename,
            file_type=file_type,
            file_size=len(file_bytes),
            status="pending",
            source_bytes=file_bytes,
        )
        db.add(doc)
        db.flush()
        _queue_ingestion(db, doc, kind="ingestion")
        db.commit()
        db.refresh(doc)
    except Exception as exc:
        db.rollback()
        try:
            release_quota(db, tenant.business_id, "documents")
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Could not release document quota after queue failure")
        logger.exception("Could not queue document ingestion")
        raise HTTPException(503, "Chưa thể xếp hàng xử lý tài liệu. Vui lòng thử lại.") from exc

    logger.info(
        "Document uploaded: %s (id=%d), processing in background",
        file.filename,
        doc.id,
    )

    return doc


@router.post("/{document_id}/reindex", response_model=DocumentOut, dependencies=[Depends(require_write_access)])
async def reindex_document(
    document_id: int,
    db: Session = Depends(get_tenant_db),
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
    if _has_active_ingestion(db, business_id=tenant.business_id, document_id=doc.id):
        raise HTTPException(409, "Tài liệu đang được xử lý; không thể tạo thêm một lượt trùng.")
    doc.status = "pending"
    doc.embedding_status = "pending"
    doc.error_message = None
    _queue_ingestion(db, doc, kind="reindex")
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/{document_id}/runs", response_model=RagRunListOut)
async def list_document_runs(document_id: int, db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context)):
    if db.query(Document.id).filter(Document.id == document_id, Document.business_id == tenant.business_id).first() is None:
        raise HTTPException(404, "Tài liệu không tồn tại.")
    runs = db.query(RagRun).filter(RagRun.document_id == document_id, RagRun.business_id == tenant.business_id).order_by(RagRun.id.desc()).limit(100).all()
    return {"items": [_run_out(row) for row in runs], "total": len(runs)}


@router.post(
    "/runs/{run_id}/retry",
    response_model=RagRunOut,
    status_code=201,
    dependencies=[Depends(require_write_access)],
)
async def retry_failed_run(
    run_id: int,
    db: Session = Depends(get_tenant_db),
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
    if _has_active_ingestion(db, business_id=tenant.business_id, document_id=doc.id):
        raise HTTPException(409, "Tài liệu đã có một lượt xử lý đang chờ hoặc đang chạy.")
    doc.status = "pending"
    doc.embedding_status = "pending"
    doc.error_message = None
    run = _queue_ingestion(db, doc, kind="retry")
    db.commit()
    db.refresh(run)
    return _run_out(run)


@router.post("/jobs/dispatch", dependencies=[Depends(require_write_access)])
async def dispatch_document_jobs(db: Session = Depends(get_tenant_db), tenant: TenantContext = Depends(get_tenant_context)):
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
    db: Session = Depends(get_tenant_db),
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
    db: Session = Depends(get_tenant_db),
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
    db: Session = Depends(get_tenant_db),
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
    db: Session = Depends(get_tenant_db),
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
