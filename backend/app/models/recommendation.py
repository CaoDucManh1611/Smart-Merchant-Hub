"""Tenant-scoped serving, feedback and training records for recommendations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.bases import TenantBase


class RecommendationRequest(TenantBase):
    __tablename__ = "recommendation_requests"
    __table_args__ = (
        UniqueConstraint("business_id", "request_id", name="uq_recommendation_request_business_request"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    experiment_id: Mapped[int | None] = mapped_column(ForeignKey("experiments.id", ondelete="SET NULL"), nullable=True, index=True)
    bandit_decision_id: Mapped[int | None] = mapped_column(ForeignKey("bandit_decisions.id", ondelete="SET NULL"), nullable=True, index=True)
    strategy: Mapped[str] = mapped_column(String(40), nullable=False)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    served_items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), index=True)


class RecommendationFeedback(TenantBase):
    __tablename__ = "recommendation_feedback"
    __table_args__ = (
        UniqueConstraint("business_id", "idempotency_key", name="uq_recommendation_feedback_business_idempotency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    recommendation_request_id: Mapped[int] = mapped_column(ForeignKey("recommendation_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    reward: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False, default=Decimal("0"))
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    event_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), index=True)


class CustomerProductInteraction(TenantBase):
    """Durable, tenant-scoped behavioral signal used by the recommender.

    ``product_id`` is optional only for search/ask events. This preserves a
    customer's RAG intent without pretending that an unlinked question names a
    particular catalog item.
    """

    __tablename__ = "customer_product_interactions"
    __table_args__ = (
        UniqueConstraint(
            "business_id",
            "idempotency_key",
            name="uq_recommendation_interaction_business_idempotency",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recommendation_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("recommendation_requests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    query_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    event_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), index=True)


class RecommendationCustomerProfile(TenantBase):
    __tablename__ = "recommendation_customer_profiles"
    __table_args__ = (
        UniqueConstraint("business_id", "customer_id", name="uq_recommendation_profile_business_customer"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    segment_label: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    features: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    trained_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class RecommendationTrainingRun(TenantBase):
    __tablename__ = "recommendation_training_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    algorithm: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    artifact: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
