"""Customer data lifecycle request contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PrivacyRequest(BaseModel):
    request_key: str = Field(..., min_length=3, max_length=180)


class PrivacyDeleteRequest(PrivacyRequest):
    confirmation_token: str = Field(..., min_length=1, max_length=40)


class PrivacyResponse(BaseModel):
    id: int
    kind: Literal["export", "anonymize", "delete"]
    status: str
    counts: dict[str, int] = Field(default_factory=dict)
    data: dict | None = None


class PrivacyRequestOut(BaseModel):
    id: int
    request_key: str
    kind: Literal["export", "anonymize", "delete"]
    status: str
    requested_by: int | None = None
    result_metadata: dict | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}
