"""Short-lived email verification challenges for public shop signup."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class SignupEmailChallenge(Base):
    __tablename__ = "signup_email_challenges"
    __table_args__ = (
        Index("ix_signup_email_challenges_email_status", "email", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    owner_name: Mapped[str] = mapped_column(String(255), nullable=False)
    shop_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # The same short-lived challenge store is also used for verified staff
    # invitations.  Existing signup rows keep the default ``signup`` purpose.
    purpose: Mapped[str] = mapped_column(String(30), nullable=False, default="signup", server_default="signup", index=True)
    business_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
