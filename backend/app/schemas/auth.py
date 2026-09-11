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
    mfa_status: str | None = None

    model_config = ConfigDict(from_attributes=True)


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: AuthUserOut
    mfa_required: bool = False


class AuthSessionOut(BaseModel):
    id: int
    device_label: str | None = None
    expires_at: datetime
    revoked_at: datetime | None = None
    last_seen_at: datetime | None = None
    mfa_verified: bool
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class MfaPrepareOut(BaseModel):
    status: str
    provisioning_uri: str


class MfaVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class MfaVerifyOut(BaseModel):
    status: str
    mfa_verified: bool = True


class MfaDisableRequest(BaseModel):
    confirm: bool = False


class AuditLogOut(BaseModel):
    id: int
    event_id: str
    business_id: int
    user_id: int | None = None
    actor_type: str = "system"
    correlation_id: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    metadata: dict = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
