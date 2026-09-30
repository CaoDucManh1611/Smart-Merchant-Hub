"""Tenant-owned application settings."""

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.bases import TenantBase


class BusinessSetting(TenantBase):
    __tablename__ = "business_settings"
    __table_args__ = (
        UniqueConstraint("business_id", "key", name="uq_business_settings_business_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
