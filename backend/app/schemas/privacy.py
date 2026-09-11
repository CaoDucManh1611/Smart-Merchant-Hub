"""Customer data lifecycle request contracts."""

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
