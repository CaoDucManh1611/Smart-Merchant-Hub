"""Minimal provider routing keys kept in the platform database."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.bases import PlatformBase


class ChannelRoute(PlatformBase):
    __tablename__ = "channel_routes"
    __table_args__ = (
        UniqueConstraint("provider", "external_account_id_hash", name="uq_channel_route_provider_account"),
        UniqueConstraint("provider", "secret_hash", name="uq_channel_route_provider_secret"),
        CheckConstraint(
            "provider IN ('telegram','zalo','facebook','instagram')",
            name="ck_channel_route_provider",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    external_account_id_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    secret_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("platform_businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    schema_name: Mapped[str] = mapped_column(String(120), nullable=False)
    channel_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
