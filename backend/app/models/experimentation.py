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
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_event_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    proposed_workflow_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    converted_workflow_id: Mapped[int | None] = mapped_column(ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True, index=True)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
    min_sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stop_criteria: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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


class ExperimentExposure(Base):
    __tablename__ = "experiment_exposures"
    __table_args__ = (
        UniqueConstraint("experiment_id", "idempotency_key", name="uq_experiment_exposure_idempotency"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    assignment_id: Mapped[int | None] = mapped_column(ForeignKey("experiment_assignments.id", ondelete="CASCADE"), nullable=True, index=True)
    subject_key: Mapped[str] = mapped_column(String(255), nullable=False)
    variant: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    exposed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class ExperimentOutcome(Base):
    __tablename__ = "experiment_outcomes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("experiment_assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ExperimentMetricAggregate(Base):
    __tablename__ = "experiment_metric_aggregates"
    __table_args__ = (
        UniqueConstraint("experiment_id", "metric", "variant", name="uq_experiment_metric_variant"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(80), nullable=False)
    variant: Mapped[str] = mapped_column(String(80), nullable=False)
    exposure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outcome_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    value_sum: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint("business_id", "name", "version", name="uq_model_version_business_name_version"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(40), nullable=False)
    target: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    artifact: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    trained_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ModelTrainingRun(Base):
    __tablename__ = "model_training_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", index=True)
    snapshot_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    train_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    holdout_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    artifact: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ModelEvaluationMetric(Base):
    __tablename__ = "model_evaluation_metrics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    training_run_id: Mapped[int] = mapped_column(ForeignKey("model_training_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(80), nullable=False)
    split: Mapped[str] = mapped_column(String(30), nullable=False, default="holdout")
    value: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)


class BanditPolicy(Base):
    __tablename__ = "bandit_policies"
    __table_args__ = (
        UniqueConstraint("experiment_id", "version", name="uq_bandit_policy_experiment_version"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    epsilon: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, default=Decimal("0.10"))
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class BanditArmStat(Base):
    __tablename__ = "bandit_arm_stats"
    __table_args__ = (
        UniqueConstraint("policy_id", "arm", "context_hash", name="uq_bandit_arm_context"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    policy_id: Mapped[int] = mapped_column(ForeignKey("bandit_policies.id", ondelete="CASCADE"), nullable=False, index=True)
    arm: Mapped[str] = mapped_column(String(80), nullable=False)
    context_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    pulls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reward_sum: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class BanditDecision(Base):
    __tablename__ = "bandit_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_key: Mapped[str] = mapped_column(String(255), nullable=False)
    arm: Mapped[str] = mapped_column(String(80), nullable=False)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    policy_id: Mapped[int | None] = mapped_column(ForeignKey("bandit_policies.id", ondelete="SET NULL"), nullable=True, index=True)
    policy_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    context_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    selection_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reward_idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reward: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
