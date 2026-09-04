"""Customer merge request/response contracts."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CustomerMergeRequest(BaseModel):
    source_customer_id: int = Field(..., ge=1)
    reason: str | None = Field(default=None, max_length=2000)


class CustomerMergePreviewOut(BaseModel):
    survivor_customer_id: int
    source_customer_id: int
    survivor_counts: dict[str, int]
    source_counts: dict[str, int]


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
