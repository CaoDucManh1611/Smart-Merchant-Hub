"""Admin publication workflow and a tenant-independent public package advisor."""
import hashlib
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.auth.platform import require_platform_admin
from app.core.config import settings
from app.database.platform_session import get_platform_db
from app.db.dependencies import get_db
from app.middleware.security import LoginRateLimiter, RateLimitBackendUnavailable
from app.models.business import User
from app.models.platform_knowledge import PlatformKnowledgeDocument
from app.rag.chunker import chunk_text
from app.rag.loader import load_document, DocumentValidationError, detect_file_type
from app.services.service_advisor import advise

router = APIRouter(tags=["Service knowledge and advice"])
MAX_BYTES = 10 * 1024 * 1024
MAX_CHARACTERS = 200000
ALLOWED_TYPES = {"pdf", "docx", "txt", "md"}


def document_out(row):
    return {"id": row.id, "filename": row.filename, "published": row.published,
            "chunk_count": len(row.chunks), "preview": row.content[:2500],
            "characters": len(row.content), "created_at": row.created_at}


@router.get("/platform/knowledge")
def list_documents(db: Session = Depends(get_platform_db), actor: User = Depends(require_platform_admin)):
    return {"items": [document_out(row) for row in db.scalars(select(PlatformKnowledgeDocument).order_by(PlatformKnowledgeDocument.id.desc()))]}


@router.post("/platform/knowledge/upload", status_code=201)
async def upload_document(file: UploadFile, db: Session = Depends(get_platform_db), actor: User = Depends(require_platform_admin)):
    try:
        filename = PurePosixPath((file.filename or "").replace("\\", "/")).name[:255]
        if not filename or detect_file_type(filename) not in ALLOWED_TYPES:
            raise HTTPException(400, "Chỉ hỗ trợ PDF, DOCX, TXT và Markdown.")
        content = await file.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise HTTPException(413, "Tài liệu tối đa 10 MB.")
        if db.scalar(select(func.count()).select_from(PlatformKnowledgeDocument)) >= 100:
            raise HTTPException(409, "Kho tư vấn tối đa 100 tài liệu. Hãy cập nhật tài liệu hiện có.")
        fingerprint = hashlib.sha256(content).hexdigest()
        if db.scalar(select(PlatformKnowledgeDocument.id).where(PlatformKnowledgeDocument.content_hash == fingerprint)):
            raise HTTPException(409, "Tài liệu này đã có trong kho tư vấn.")
        try:
            extracted = await run_in_threadpool(load_document, content, filename)
        except DocumentValidationError as error:
            raise HTTPException(400, str(error)) from None
        except Exception:
            raise HTTPException(400, "Không đọc được tài liệu. Hãy dùng tệp có văn bản; PDF ảnh cần nhận dạng chữ trước.") from None
        if len(extracted) > MAX_CHARACTERS:
            raise HTTPException(413, "Tài liệu quá dài. Hãy chia thành các tệp dưới 200.000 ký tự.")
        chunks = [chunk.content for chunk in chunk_text(extracted, chunk_size=1200, chunk_overlap=120)]
        row = PlatformKnowledgeDocument(filename=filename, content_hash=fingerprint, content=extracted,
                                        chunks=chunks, published=False, created_by=actor.id)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "Tài liệu này đã có trong kho tư vấn.") from None
        return document_out(row)
    finally:
        await file.close()


class Publication(BaseModel):
    published: bool


@router.patch("/platform/knowledge/{document_id}")
def publish_document(document_id: int, body: Publication, db: Session = Depends(get_platform_db), actor: User = Depends(require_platform_admin)):
    row = db.get(PlatformKnowledgeDocument, document_id)
    if row is None:
        raise HTTPException(404, "Không tìm thấy tài liệu.")
    row.published = body.published
    db.commit()
    return document_out(row)


class AdvisorMessage(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1500)


class AdvisorQuestion(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    question: str = Field(min_length=1, max_length=1000)
    history: list[AdvisorMessage] = Field(default_factory=list, max_length=6)
    locale: Literal["vi", "en"] = "vi"


@lru_cache(maxsize=1)
def advisor_limiter():
    return LoginRateLimiter(enabled=True, max_attempts=12, window_seconds=60,
                            backend="redis" if settings.REDIS_URL else "memory",
                            redis_url=settings.REDIS_URL, prefix="crm:service-advisor:")


@lru_cache(maxsize=1)
def advisor_daily_limiter():
    return LoginRateLimiter(enabled=True, max_attempts=settings.SERVICE_ADVISOR_DAILY_LIMIT, window_seconds=86400,
                            backend="redis" if settings.REDIS_URL else "memory",
                            redis_url=settings.REDIS_URL, prefix="crm:service-advisor-budget:")


@router.post("/services/advisor/chat")
def service_advice(body: AdvisorQuestion, request: Request, db: Session = Depends(get_platform_db), catalogue_db: Session = Depends(get_db)):
    try:
        # Use the actual peer, never a user-controlled X-Forwarded-For header.
        peer = request.client.host if request.client else "unknown"
        decision = advisor_limiter().record_failure(peer)
        if not decision.allowed:
            raise HTTPException(429, "Bạn gửi câu hỏi quá nhanh. Vui lòng chờ một chút.", headers={"Retry-After": str(decision.retry_after)})
        daily = advisor_daily_limiter().record_failure("all-visitors")
        if not daily.allowed:
            raise HTTPException(429, "Tư vấn tự động đã đạt giới hạn hôm nay. Vui lòng xem bảng giá hoặc liên hệ hỗ trợ.", headers={"Retry-After": str(daily.retry_after)})
    except RateLimitBackendUnavailable:
        raise HTTPException(503, "Tư vấn tạm thời chưa sẵn sàng. Vui lòng thử lại sau.") from None
    return advise(db, catalogue_db, body.question, [item.model_dump() for item in body.history], body.locale)
