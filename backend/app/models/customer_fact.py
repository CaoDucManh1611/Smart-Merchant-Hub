"""Tenant-scoped facts inferred or confirmed for a customer profile."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class CustomerFact(Base):
    __tablename__ = "customer_facts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )

    fact_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    fact_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    fact_value_json: Mapped[Any] = mapped_column("fact_value_json", JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)

    source_type: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    source_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )

    observed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    extractor: Mapped[str | None] = mapped_column(String(80), nullable=True)
    extractor_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    business = relationship("Business")
    customer = relationship("Customer", back_populates="facts")
    source_message = relationship("Message", foreign_keys=[source_message_id])
    source_order = relationship("Order", foreign_keys=[source_order_id])
