"""Short-lived verification challenges for changing a user's login email."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class UserEmailChangeChallenge(Base):
    __tablename__ = "user_email_change_challenges"
    __table_args__ = (
        Index("ix_user_email_change_user_id", "user_id"),
        Index("ix_user_email_change_business_id", "business_id"),
        Index("ix_user_email_change_status", "status"),
        Index("ix_user_email_change_user_status_created", "user_id", "status", "created_at"),
        Index("ix_user_email_change_email_status", "new_email", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    new_email: Mapped[str] = mapped_column(String(255), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending_delivery", server_default="pending_delivery")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
