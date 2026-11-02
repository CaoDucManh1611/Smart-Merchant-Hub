"""Per-shop gate state for learned recommendation ranking."""
from __future__ import annotations
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Integer, JSON, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database.bases import TenantBase

class RecommendationShopModelState(TenantBase):
    __tablename__ = "recommendation_shop_model_states"
    __table_args__ = (UniqueConstraint("business_id", name="uq_rs_model_business"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(40), nullable=False, default="baseline")
    model_version: Mapped[str | None] = mapped_column(String(120))
    gate_status: Mapped[str] = mapped_column(String(20), nullable=False, default="baseline")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consented_customer_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    baseline_ndcg: Mapped[float | None] = mapped_column(Numeric(10, 6))
    candidate_ndcg: Mapped[float | None] = mapped_column(Numeric(10, 6))
    baseline_violation_rate: Mapped[float | None] = mapped_column(Numeric(10, 6))
    candidate_violation_rate: Mapped[float | None] = mapped_column(Numeric(10, 6))
    train_window: Mapped[dict | None] = mapped_column(JSON)
    holdout_window: Mapped[dict | None] = mapped_column(JSON)
    metrics: Mapped[dict | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
