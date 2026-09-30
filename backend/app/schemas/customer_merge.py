"""Customer 360 duplicate, merge and saved-segment contracts."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CustomerMergeRequest(BaseModel):
    source_customer_id: int = Field(..., ge=1)
    reason: str | None = Field(default=None, max_length=2000)
    # Keep the default true for compatibility with the original merge API.
    # New UI flows always send this explicitly after showing the preview.
    confirm: bool = True


class CustomerMergePreviewOut(BaseModel):
    survivor_customer_id: int
    source_customer_id: int
    survivor_counts: dict[str, int]
    source_counts: dict[str, int]
    confidence_score: float = 0.0
    confidence_label: str = "unknown"
    matched_fields: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    can_merge: bool = True


class CustomerMergeOut(BaseModel):
    merge_id: int
    business_id: int
    survivor_customer_id: int
    source_customer_id: int
    status: str
    reason: str | None = None
    before_counts: dict[str, Any]
    after_counts: dict[str, Any]
    created_at: datetime | None = None
    confidence_score: float | None = None
    confidence_label: str | None = None
    matched_fields: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    undone_at: datetime | None = None
    can_undo: bool = False


class CustomerDuplicateSuggestionOut(BaseModel):
    survivor_customer_id: int
    source_customer_id: int
    survivor_name: str | None = None
    source_name: str | None = None
    survivor_channel: str
    source_channel: str
    confidence_score: float
    confidence_label: str
    matched_fields: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class CustomerMergeUndoRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class CustomerSegmentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    tag_ids: list[int] = Field(..., min_length=1, max_length=50)
    match_mode: Literal["all", "any"] = "all"


class CustomerSegmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    tag_ids: list[int] | None = Field(default=None, min_length=1, max_length=50)
    match_mode: Literal["all", "any"] | None = None


class CustomerSegmentOut(BaseModel):
    id: int
    business_id: int
    name: str
    description: str | None = None
    tag_ids: list[int] = Field(default_factory=list)
    match_mode: Literal["all", "any"]
    customer_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
