from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.bases import TenantBase


class ChannelMigrationAudit(TenantBase):
    __tablename__ = "channel_migration_audits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    channel_type: Mapped[str] = mapped_column(String(30), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    business_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    report: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
