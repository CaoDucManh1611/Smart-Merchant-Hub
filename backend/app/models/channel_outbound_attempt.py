"""Durable idempotency state for outbound channel messages."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.bases import TenantBase


class ChannelOutboundAttempt(TenantBase):
    __tablename__ = "channel_outbound_attempts"
    __table_args__ = (
        UniqueConstraint("business_id", "client_id", name="uq_channel_outbound_attempts_client"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("channels.id", ondelete="SET NULL"), nullable=True
    )
    business_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="processing", index=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
