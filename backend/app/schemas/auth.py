"""Authentication API contracts."""

from datetime import datetime
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=256)
    shop_slug: str | None = Field(default=None, min_length=2, max_length=120)
    remember_me: bool = False


class PasswordResetRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    shop_slug: str | None = Field(default=None, min_length=2, max_length=120)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
            raise ValueError("Email không hợp lệ.")
        return normalized


class PasswordResetComplete(PasswordResetRequest):
    otp: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")
    new_password: str = Field(..., min_length=12, max_length=256)


class PasswordResetRequestOut(BaseModel):
    status: str
    expires_in: int
    retry_after: int


class PasswordResetCompleteOut(BaseModel):
    status: str


class EmailChangeRequest(BaseModel):
    new_email: str = Field(..., min_length=3, max_length=255)
    current_password: str = Field(..., min_length=1, max_length=256)

    @field_validator("new_email")
    @classmethod
    def validate_new_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
            raise ValueError("Email mới không hợp lệ.")
        return normalized


class EmailChangeVerify(BaseModel):
    otp: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class EmailChangeRequestOut(BaseModel):
    status: str
    email: str
    expires_in: int
    retry_after: int


class EmailChangeVerifyOut(BaseModel):
    status: str
    email: str


class AuthUserOut(BaseModel):
    id: int
    # Platform administrators are control-plane identities and do not belong
    # to any shop tenant. Shop users still always receive an integer id.
    business_id: int | None = None
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
