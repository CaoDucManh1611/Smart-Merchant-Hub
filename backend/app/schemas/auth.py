"""Authentication API contracts."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=256)


class AuthUserOut(BaseModel):
    id: int
    business_id: int
    full_name: str
    email: str
    role: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: AuthUserOut


class AuditLogOut(BaseModel):
    id: int
    business_id: int
    user_id: int | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    metadata: dict = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
