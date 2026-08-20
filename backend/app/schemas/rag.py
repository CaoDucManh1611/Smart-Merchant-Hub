"""
Pydantic schemas cho RAG APIs: Document upload, chat.
"""

from datetime import datetime

from pydantic import BaseModel, Field


# =========================================================
# DOCUMENT SCHEMAS
# =========================================================


class DocumentOut(BaseModel):
    id: int
    filename: str
    file_type: str
    file_size: int
    status: str
    chunk_count: int
    error_message: str | None = None
    uploaded_at: datetime
    processed_at: datetime | None = None

    model_config = {"from_attributes": True}


class DocumentListOut(BaseModel):
    documents: list[DocumentOut]
    total: int


class DocumentChunkOut(BaseModel):
    id: int
    document_id: int
    chunk_index: int
    content: str
    metadata: dict | None = None
    has_embedding: bool


# =========================================================
# CHAT SCHEMAS
# =========================================================


class ChatRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Câu hỏi của user",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Số lượng chunks tham khảo tối đa",
    )
    conversation_history: list[dict] | None = Field(
        default=None,
        description="Lịch sử hội thoại [{role, content}, ...]",
    )


class SourceChunk(BaseModel):
    document_id: int
    content: str
    similarity: float
    metadata: dict | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    chunks_found: int
