"""Tenant team directory and role schemas."""

from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth.passwords import validate_signup_password


TEAM_ROLES = ("owner", "admin", "agent", "viewer", "business_agent")
TeamRole = Literal["owner", "admin", "agent", "viewer", "business_agent"]
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

# Older installs used ``business_agent`` (and the platform database used
# ``shop_agent``) for the same human-facing role.  Keep accepting those
# values at the API boundary, but persist the four canonical roles so every
# shop sees the same permissions and labels.
ROLE_ALIASES = {
    "business_agent": "agent",
    "shop_agent": "agent",
    "business_admin": "admin",
    "shop_admin": "admin",
}


def normalize_team_role(role: str | None) -> str:
    value = str(role or "agent").strip().lower()
    return ROLE_ALIASES.get(value, value if value in {"owner", "admin", "agent", "viewer"} else "agent")


class TeamUserCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=3, max_length=255)
    role: TeamRole = "agent"
    password: str | None = Field(default=None, min_length=12, max_length=256)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _EMAIL_RE.fullmatch(normalized):
            raise ValueError("Email công việc không hợp lệ.")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str | None) -> str | None:
        return validate_signup_password(value) if value is not None else value


class TeamOtpRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=3, max_length=255)
    role: TeamRole = "agent"
    password: str = Field(..., min_length=12, max_length=256)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _EMAIL_RE.fullmatch(normalized):
            raise ValueError("Email công việc không hợp lệ.")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        return validate_signup_password(value)


class TeamOtpVerify(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    otp: str = Field(..., min_length=6, max_length=6)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _EMAIL_RE.fullmatch(normalized):
            raise ValueError("Email công việc không hợp lệ.")
        return normalized

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.isdigit():
            raise ValueError("Mã OTP phải gồm 6 chữ số.")
        return normalized


class TeamOtpOut(BaseModel):
    status: str
    email: str
    expires_in: int


class TeamUserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    role: TeamRole | None = None
    is_active: bool | None = None


class TeamUserOut(BaseModel):
    id: int
    business_id: int
    full_name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TeamUserListOut(BaseModel):
    items: list[TeamUserOut]
    total: int


class PermissionOverrideCreate(BaseModel):
    resource: str = Field(..., min_length=1, max_length=80)
    action: str = Field(..., min_length=1, max_length=40)
    effect: str = Field(..., pattern="^(allow|deny)$")
    role: str | None = Field(default=None, max_length=40)
    user_id: int | None = None


class PermissionOverrideOut(BaseModel):
    id: int
    business_id: int
    resource: str
    action: str
    effect: str
    role: str | None = None
    user_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PermissionOverrideListOut(BaseModel):
    items: list[PermissionOverrideOut]
    total: int


class EffectivePermissionOut(BaseModel):
    resource: str
    action: str
    allowed: bool
    source: str


class EffectivePermissionListOut(BaseModel):
    user_id: int
    items: list[EffectivePermissionOut]
