"""
Document & DocumentChunk models for RAG knowledge base.

Document  – metadata về file gốc (tên, loại, trạng thái xử lý).
DocumentChunk – từng đoạn text đã được chunk + vector embedding.
"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.core.config import settings


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    business_id: Mapped[int | None] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    filename: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    file_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
    )

    file_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default="pending",
        index=True,
    )
    # pending → processing → ready → error

    chunk_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    embedding_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default="pending", index=True
    )
    reindex_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    retry_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )

    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    chunks = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
    )

    business = relationship("Business", back_populates="documents")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    embedding = mapped_column(
        Vector(settings.EMBEDDING_DIMENSION),
        nullable=True,
    )

    metadata_: Mapped[dict | None] = mapped_column(
        "metadata",
        JSON,
        nullable=True,
    )
    # page number, section, source info...

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )

    document = relationship(
        "Document",
        back_populates="chunks",
    )
