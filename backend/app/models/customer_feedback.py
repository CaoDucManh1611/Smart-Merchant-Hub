"""Tenant-scoped customer satisfaction feedback for resolved conversations."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class CustomerFeedback(Base):
    __tablename__ = "customer_feedback"
    __table_args__ = (
        UniqueConstraint("business_id", "idempotency_key", name="uq_customer_feedback_business_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True, index=True)
    followup_id: Mapped[int | None] = mapped_column(ForeignKey("chatbot_followups.id", ondelete="SET NULL"), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled", server_default="scheduled", index=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    business = relationship("Business")
    conversation = relationship("Conversation")
    customer = relationship("Customer")
    ticket = relationship("Ticket")
    followup = relationship("ChatbotFollowUp")
