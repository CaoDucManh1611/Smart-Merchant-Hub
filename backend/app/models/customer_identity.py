"""External channel identities linked to a canonical CRM customer."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class CustomerIdentity(Base):
    __tablename__ = "customer_identities"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "channel",
            "external_account_id",
            "external_user_id",
            name="uq_customer_identity_business_channel_account_user",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    business = relationship("Business")
    customer = relationship("Customer", back_populates="identities")
