"""Tenant-scoped recommendation and experimentation primitives."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class RuleSuggestion(Base):
    __tablename__ = "rule_suggestions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_id: Mapped[int | None] = mapped_column(ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_action: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FeatureSnapshot(Base):
    __tablename__ = "feature_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True)
    feature_version: Mapped[str] = mapped_column(String(40), nullable=False)
    features: Mapped[dict] = mapped_column(JSON, nullable=False)
    label: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    variants: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ExperimentAssignment(Base):
    __tablename__ = "experiment_assignments"
    __table_args__ = (UniqueConstraint("experiment_id", "subject_key", name="uq_experiment_assignment_subject"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_key: Mapped[str] = mapped_column(String(255), nullable=False)
    variant: Mapped[str] = mapped_column(String(80), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ExperimentOutcome(Base):
    __tablename__ = "experiment_outcomes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("experiment_assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BanditDecision(Base):
    __tablename__ = "bandit_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_key: Mapped[str] = mapped_column(String(255), nullable=False)
    arm: Mapped[str] = mapped_column(String(80), nullable=False)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    reward: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
