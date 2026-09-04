"""Safe recommendation and experimentation API contracts."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field


class RuleSuggestionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    rationale: str = Field(..., min_length=1, max_length=5000)
    proposed_action: dict[str, Any]
    workflow_id: int | None = Field(default=None, ge=1)


class RuleSuggestionReview(BaseModel):
    status: Literal["accepted", "rejected"]


class RuleSuggestionOut(BaseModel):
    id: int
    business_id: int
    workflow_id: int | None = None
    title: str
    rationale: str
    proposed_action: dict[str, Any]
    status: str
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    created_at: datetime | None = None


class FeatureSnapshotCreate(BaseModel):
    customer_id: int | None = Field(default=None, ge=1)
    feature_version: str = Field(..., min_length=1, max_length=40)
    features: dict[str, Any]
    label: dict[str, Any] | None = None


class FeatureSnapshotOut(FeatureSnapshotCreate):
    id: int
    business_id: int
    captured_at: datetime | None = None


class ExperimentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    variants: list[str] = Field(..., min_length=2, max_length=20)
    status: Literal["draft", "running", "paused", "completed"] = "draft"


class ExperimentOut(BaseModel):
    id: int
    business_id: int
    name: str
    variants: list[str]
    status: str
    created_at: datetime | None = None


class AssignmentRequest(BaseModel):
    subject_key: str = Field(..., min_length=1, max_length=255)
    variant: str | None = Field(default=None, max_length=80)


class AssignmentOut(BaseModel):
    id: int
    experiment_id: int
    subject_key: str
    variant: str
    assigned_at: datetime | None = None


class OutcomeRequest(BaseModel):
    metric: str = Field(..., min_length=1, max_length=80)
    value: Decimal


class OutcomeOut(OutcomeRequest):
    id: int
    assignment_id: int
    created_at: datetime | None = None


class BanditDecisionRequest(BaseModel):
    subject_key: str = Field(..., min_length=1, max_length=255)
    arm: str = Field(..., min_length=1, max_length=80)
    context: dict[str, Any] = Field(default_factory=dict)


class BanditDecisionOut(BanditDecisionRequest):
    id: int
    experiment_id: int
    reward: Decimal | None = None
    decided_at: datetime | None = None
