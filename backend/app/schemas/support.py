"""Safe contracts for owner-approved operational support access."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SupportScope = Literal["settings:read", "channels:diagnose", "jobs:retry"]
_ALLOWED_SCOPES = {"settings:read", "channels:diagnose", "jobs:retry"}


class SupportGrantCreate(BaseModel):
    support_user_id: int = Field(..., gt=0)
    reason: str = Field(..., min_length=8, max_length=500)
    scopes: list[SupportScope] = Field(..., min_length=1, max_length=3)
    expires_at: datetime

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 8:
            raise ValueError("reason phải có ít nhất 8 ký tự")
        return value

    @field_validator("scopes")
    @classmethod
    def unique_scopes(cls, value: list[str]) -> list[str]:
        normalized = [str(item).strip().lower() for item in value]
        if len(set(normalized)) != len(normalized) or not set(normalized) <= _ALLOWED_SCOPES:
            raise ValueError("scope không được phép hoặc bị lặp")
        return normalized


class SupportGrantOut(BaseModel):
    id: int
    business_id: int
    granted_by_user_id: int
    support_user_id: int
    reason: str
    scopes: list[str]
    expires_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class SupportSessionCreate(BaseModel):
    grant_id: int = Field(..., gt=0)


class SupportSessionOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    grant_id: int
    business_id: int
    scopes: list[str]
