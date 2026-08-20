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

logger = logging.getLogger(__name__)

router = APIRouter()


def _run_ingestion_background(
    document_id: int,
    file_bytes: bytes,
    filename: str,
) -> None:
    """Chạy ingestion trong thread riêng với DB session riêng."""
    db = SessionLocal()
    try:
        ingest_document(document_id, file_bytes, filename, db)
    finally:
        db.close()


# =========================================================
# UPLOAD
# =========================================================


@router.post(
    "/upload",
    response_model=DocumentOut,
    status_code=201,
)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
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
        filename=file.filename,
        file_type=file_type,
        file_size=len(file_bytes),
        status="pending",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Chạy ingestion trong background thread
    thread = Thread(
        target=_run_ingestion_background,
        args=(doc.id, file_bytes, file.filename),
        daemon=True,
    )
    thread.start()

    logger.info(
        "Document uploaded: %s (id=%d), processing in background",
        file.filename,
        doc.id,
    )

    return doc


# =========================================================
# LIST
# =========================================================


@router.get("", response_model=DocumentListOut)
async def list_documents(
    db: Session = Depends(get_db),
):
    """Danh sách tất cả tài liệu đã upload."""
    docs = (
        db.query(Document)
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
):
    """Xem chi tiết 1 tài liệu."""
    doc = db.get(Document, document_id)
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
):
    """Xem các chunks đã tạo và trạng thái embedding của một tài liệu."""
    if db.get(Document, document_id) is None:
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


@router.delete("/{document_id}", status_code=204)
async def remove_document(
    document_id: int,
    db: Session = Depends(get_db),
):
    """Xóa tài liệu và tất cả chunks liên quan."""
    deleted = delete_document(document_id, db)
    if not deleted:
        raise HTTPException(404, "Tài liệu không tồn tại.")
    return None
