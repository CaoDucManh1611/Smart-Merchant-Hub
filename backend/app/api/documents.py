"""
Document Management API – upload, list, delete tài liệu.
"""

import logging
from threading import Thread

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.dependencies import get_db
from app.models.document import Document, DocumentChunk
from app.rag.loader import detect_file_type, LOADERS
from app.schemas.rag import DocumentChunkOut, DocumentListOut, DocumentOut
from app.services.ingestion_service import (
    delete_document,
    ingest_document,
)
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.auth.dependencies import require_write_access

logger = logging.getLogger(__name__)

router = APIRouter()


def _run_ingestion_background(
    document_id: int,
    file_bytes: bytes,
    filename: str,
    business_id: int,
) -> None:
    """Chạy ingestion trong thread riêng với DB session riêng."""
    db = SessionLocal()
    try:
        ingest_document(document_id, file_bytes, filename, db, business_id=business_id)
    finally:
        db.close()


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

    # Chạy ingestion trong background thread
    thread = Thread(
        target=_run_ingestion_background,
        args=(doc.id, file_bytes, file.filename, tenant.business_id),
        daemon=True,
    )
    thread.start()

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
    thread = Thread(
        target=_run_ingestion_background,
        args=(doc.id, source, doc.filename, tenant.business_id),
        daemon=True,
    )
    thread.start()
    db.refresh(doc)
    return doc


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
    deleted = delete_document(document_id, db, business_id=tenant.business_id)
    if not deleted:
        raise HTTPException(404, "Tài liệu không tồn tại.")
    return None
