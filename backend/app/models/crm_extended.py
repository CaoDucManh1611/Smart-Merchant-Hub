"""CRM assignment and conversation label models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.bases import TenantBase


class ConversationAssignment(TenantBase):
    __tablename__ = "conversation_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )
    assigned_by: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    assignment_type: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    assigned_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    conversation = relationship("Conversation", back_populates="assignments")


class Tag(TenantBase):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("business_id", "name", name="uq_tags_business_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversations = relationship("ConversationTag", back_populates="tag", cascade="all, delete-orphan")


class ConversationTag(TenantBase):
    __tablename__ = "conversation_tags"
    __table_args__ = (
        UniqueConstraint("conversation_id", "tag_id", name="uq_conversation_tags_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversation = relationship("Conversation", back_populates="tag_links")
    tag = relationship("Tag", back_populates="conversations")


class CustomerTag(TenantBase):
    """Tenant-scoped labels that belong to a customer across conversations."""

    __tablename__ = "customer_tags"
    __table_args__ = (
        UniqueConstraint("customer_id", "tag_id", name="uq_customer_tags_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        index=True,
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    customer = relationship("Customer")
    tag = relationship("Tag")
