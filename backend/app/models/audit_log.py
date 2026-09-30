"""Append-only tenant audit records."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.bases import TenantBase


class AuditLog(TenantBase):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True, default=lambda: uuid4().hex)
    business_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False, default="system", server_default="system", index=True)
    correlation_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
