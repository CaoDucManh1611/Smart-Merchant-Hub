"""Safe API contracts for owner-approved support access."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SupportGrantCreate(BaseModel):
    support_user_id: int = Field(..., gt=0)
    reason: str = Field(..., min_length=5, max_length=2000)
    scopes: list[str] = Field(..., min_length=1, max_length=8)
    expires_at: datetime


class SupportGrantOut(BaseModel):
    id: int
    business_id: int
    granted_by_user_id: int
    support_user_id: int
    reason: str
    scopes: list[str]
    expires_at: datetime
    revoked_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class SupportSessionCreate(BaseModel):
    grant_id: int = Field(..., gt=0)


class SupportSessionOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    grant_id: int
    business_id: int
    scopes: list[str]
    expires_at: datetime
