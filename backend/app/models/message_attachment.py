"""Tenant-owned media attachments associated with a message."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, JSON, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class MessageAttachment(Base):
    __tablename__ = "message_attachments"
    __table_args__ = (
        Index("ix_message_attachments_business_id", "business_id"),
        Index("ix_message_attachments_message_id", "message_id"),
        Index("ix_message_attachments_channel_id", "channel_id"),
        Index(
            "uq_message_attachments_message_external",
            "channel_id",
            "message_id",
            "external_attachment_id",
            unique=True,
            postgresql_where=text("external_attachment_id IS NOT NULL"),
            sqlite_where=text("external_attachment_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[int] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    media_type: Mapped[str] = mapped_column(String(30), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_attachment_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    message = relationship("Message", back_populates="attachments")
    channel = relationship("Channel")
