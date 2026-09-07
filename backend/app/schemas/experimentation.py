"""Safe recommendation and experimentation API contracts."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RuleSuggestionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    rationale: str = Field(..., min_length=1, max_length=5000)
    proposed_action: dict[str, Any]
    workflow_id: int | None = Field(default=None, ge=1)
    evidence: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[Any] = Field(default_factory=list, max_length=500)
    source_event_ids: list[str] = Field(default_factory=list, max_length=500)
    proposed_workflow_version: str | None = Field(default=None, max_length=40)


class RuleSuggestionReview(BaseModel):
    status: Literal["accepted", "rejected"]
    reviewer_note: str | None = Field(default=None, max_length=2000)


class RuleSuggestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int
    business_id: int
    workflow_id: int | None = None
    title: str
    rationale: str
    proposed_action: dict[str, Any]
    evidence: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[Any] = Field(default_factory=list)
    source_event_ids: list[str] = Field(default_factory=list)
    proposed_workflow_version: str | None = None
    status: str
    reviewed_by: int | None = None
    reviewer_note: str | None = None
    reviewed_at: datetime | None = None
    converted_workflow_id: int | None = None
    converted_at: datetime | None = None
    rolled_back_at: datetime | None = None
    created_at: datetime | None = None


class RuleSuggestionGenerate(BaseModel):
    channel: str = Field(..., min_length=1, max_length=80)
    sample_size: int = Field(..., ge=1, le=1_000_000)
    tag: str = Field(default="khach moi", min_length=1, max_length=80)
    source_event_ids: list[str] = Field(default_factory=list, max_length=500)
    evidence_refs: list[Any] = Field(default_factory=list, max_length=500)
    evidence: dict[str, Any] = Field(default_factory=dict)


class RuleSuggestionConvertOut(BaseModel):
    suggestion: RuleSuggestionOut
    workflow_id: int
    workflow_status: str


class FeatureSnapshotCreate(BaseModel):
    customer_id: int | None = Field(default=None, ge=1)
    feature_version: str = Field(..., min_length=1, max_length=40)
    features: dict[str, Any]
    label: dict[str, Any] | None = None


class FeatureSnapshotOut(FeatureSnapshotCreate):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int
    business_id: int
    captured_at: datetime | None = None


class ModelVersionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    version: str = Field(..., min_length=1, max_length=40)
    feature_version: str = Field(..., min_length=1, max_length=40)
    target: str = Field(..., min_length=1, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelVersionOut(ModelVersionCreate):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int
    business_id: int
    status: str
    artifact: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    trained_at: datetime | None = None


class ModelTrainRequest(BaseModel):
    snapshot_ids: list[int] | None = Field(default=None, max_length=1_000_000)
    holdout_ratio: float = Field(default=0.2, gt=0, lt=1)


class ModelTrainingRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int
    business_id: int
    model_version_id: int
    status: str
    snapshot_ids: list[int]
    train_count: int
    holdout_count: int
    metrics: dict[str, Any]
    artifact: dict[str, Any]
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ModelInferenceRequest(BaseModel):
    features: dict[str, Any]


class ModelInferenceOut(BaseModel):
    model_version_id: int
    model_version: str
    prediction: Any
    confidence: float
    feature_snapshot_time: datetime | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class ExperimentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    variants: list[str] = Field(..., min_length=2, max_length=20)
    status: Literal["draft", "running", "paused", "completed"] = "draft"
    min_sample_size: int = Field(default=0, ge=0, le=10_000_000)
    stop_criteria: dict[str, Any] = Field(default_factory=dict)


class ExperimentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int
    business_id: int
    name: str
    variants: list[str]
    status: str
    min_sample_size: int = 0
    stop_criteria: dict[str, Any] = Field(default_factory=dict)
    stopped_at: datetime | None = None
    created_at: datetime | None = None


class AssignmentRequest(BaseModel):
    subject_key: str = Field(..., min_length=1, max_length=255)
    variant: str | None = Field(default=None, max_length=80)


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int
    experiment_id: int
    subject_key: str
    variant: str
    assigned_at: datetime | None = None


class OutcomeRequest(BaseModel):
    metric: str = Field(default="conversion", min_length=1, max_length=80)
    value: Decimal
    idempotency_key: str | None = Field(default=None, max_length=160)


class OutcomeOut(OutcomeRequest):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int
    assignment_id: int
    created_at: datetime | None = None


class ExposureRequest(BaseModel):
    subject_key: str = Field(..., min_length=1, max_length=255)
    variant: str = Field(..., min_length=1, max_length=80)
    idempotency_key: str | None = Field(default=None, max_length=160)


class ExposureOut(ExposureRequest):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int
    experiment_id: int
    assignment_id: int | None = None
    exposed_at: datetime | None = None


class ExperimentArmReport(BaseModel):
    variant: str
    exposures: int
    outcomes: int
    value_sum: Decimal
    conversion_rate: float
    confidence_interval: list[float]


class ExperimentReportOut(BaseModel):
    experiment_id: int
    status: str
    stopped: bool
    min_sample_size: int
    arms: list[ExperimentArmReport]
    metrics: list[str]


class BanditDecisionRequest(BaseModel):
    subject_key: str = Field(..., min_length=1, max_length=255)
    arm: str | None = Field(default=None, min_length=1, max_length=80)
    context: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=160)


class BanditDecisionOut(BanditDecisionRequest):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int
    experiment_id: int
    reward: Decimal | None = None
    policy_id: int | None = None
    policy_version: str | None = None
    context_hash: str | None = None
    selection_reason: str | None = None
    decided_at: datetime | None = None


class BanditPolicyCreate(BaseModel):
    version: str = Field(..., min_length=1, max_length=40)
    epsilon: Decimal = Field(default=Decimal("0.10"), ge=0, le=1)
    config: dict[str, Any] = Field(default_factory=dict)
    status: Literal["active", "paused", "archived"] = "active"


class BanditPolicyOut(BanditPolicyCreate):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
    id: int
    business_id: int
    experiment_id: int
    created_at: datetime | None = None


class BanditSelectRequest(BaseModel):
    subject_key: str = Field(..., min_length=1, max_length=255)
    context: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=160)
