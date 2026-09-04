"""CRM assignment and conversation label models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class ConversationAssignment(Base):
    __tablename__ = "conversation_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assigned_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    assignment_type: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    assigned_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    conversation = relationship("Conversation", back_populates="assignments")
    user = relationship("User", foreign_keys=[user_id], back_populates="assignments")
    assigned_by_user = relationship("User", foreign_keys=[assigned_by])


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("business_id", "name", name="uq_tags_business_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversations = relationship("ConversationTag", back_populates="tag", cascade="all, delete-orphan")


class ConversationTag(Base):
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
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversation = relationship("Conversation", back_populates="tag_links")
    tag = relationship("Tag", back_populates="conversations")


class CustomerTag(Base):
    """Tenant-scoped labels that belong to a customer across conversations."""

    __tablename__ = "customer_tags"
    __table_args__ = (
        UniqueConstraint("customer_id", "tag_id", name="uq_customer_tags_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"),
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
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    customer = relationship("Customer")
    tag = relationship("Tag")
