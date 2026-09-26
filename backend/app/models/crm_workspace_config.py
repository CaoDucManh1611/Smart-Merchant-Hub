"""Tenant-defined CRM fields and lead pipeline stages."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.bases import TenantBase


class CrmWorkspaceConfig(TenantBase):
    __tablename__ = "crm_workspace_configs"
    __table_args__ = (UniqueConstraint("business_id", name="uq_crm_workspace_configs_business"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    customer_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    pipeline_stages: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
