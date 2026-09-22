"""Contracts for self-service tenant onboarding."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.auth.passwords import validate_signup_password


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class OnboardingPlanOut(BaseModel):
    id: int
    code: str
    name: str
    description: str | None = None
    price: Decimal
    billing_cycle: str
    max_users: int
    max_channels: int
    max_documents: int
    max_rag_chunks: int
    max_ai_calls: int
    max_ai_cost: Decimal
    features: dict | None = None

    model_config = ConfigDict(from_attributes=True)


class OnboardingShopCreate(BaseModel):
    shop_name: str = Field(..., min_length=2, max_length=255)
    slug: str | None = Field(default=None, min_length=2, max_length=120)
    owner_name: str = Field(..., min_length=2, max_length=255)
    owner_email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=256)
    plan_code: str = Field(default="starter", min_length=2, max_length=50)

    @field_validator("owner_email")
    @classmethod
    def validate_owner_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _EMAIL_RE.fullmatch(normalized):
            raise ValueError("Email chủ shop không hợp lệ.")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        return validate_signup_password(value)


class SignupOtpRequest(BaseModel):
    """Details collected before an email address is verified."""

    owner_name: str = Field(..., min_length=2, max_length=255)
    email: str = Field(..., min_length=3, max_length=255)
    shop_name: str = Field(..., min_length=2, max_length=255)
    password: str = Field(..., min_length=8, max_length=256)

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


class SignupOtpVerify(BaseModel):
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


class SignupOtpOut(BaseModel):
    status: str
    email: str
    expires_in: int


class OnboardingSubscriptionOut(BaseModel):
    id: int
    plan_code: str
    plan_name: str
    status: str
    service_type: Literal["package", "chatbot"] = "package"


class OnboardingPlanPurchase(BaseModel):
    """Package request submitted by an authenticated shop operator.

    Paid plans are queued for a platform administrator; the free Demo plan
    remains immediately usable in local demonstrations by shop admins only.
    """

    plan_code: str = Field(..., min_length=2, max_length=50)
    service_type: Literal["package", "chatbot"] = "package"
    contact_name: str | None = Field(default=None, max_length=120)
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=30)
    shop_name: str | None = Field(default=None, max_length=160)
    channels: list[Literal["Facebook", "Instagram", "Telegram", "Zalo", "TikTok", "Shopee"]] = Field(
        default_factory=list,
        max_length=6,
    )
    notes: str | None = Field(default=None, max_length=1000)

    @field_validator("contact_name", "contact_email", "contact_phone", "shop_name", "notes", mode="before")
    @classmethod
    def strip_optional_request_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("contact_email")
    @classmethod
    def validate_contact_email(cls, value: str | None) -> str | None:
        if value is not None and not _EMAIL_RE.fullmatch(value):
            raise ValueError("Email liên hệ không hợp lệ.")
        return value.lower() if value is not None else None

    @field_validator("channels")
    @classmethod
    def reject_duplicate_channels(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Kênh kết nối không được chọn lặp lại.")
        return value


class OnboardingBuyerOut(BaseModel):
    """The real shop contact shown on the package page."""

    name: str
    email: str
    phone: str | None = None
    shop_name: str


class OnboardingSubscriptionSummaryOut(BaseModel):
    """Subscription and payment details scoped to one authenticated shop."""

    business_id: int
    buyer: OnboardingBuyerOut
    subscription: OnboardingSubscriptionOut | None = None
    chatbot_subscription: OnboardingSubscriptionOut | None = None
    amount: Decimal | None = None
    currency: str = "VND"
    payment_status: str | None = None
    paid_at: datetime | None = None
    connected_channels: int = 0
    channel_limit: int | None = None


class OnboardingShopOut(BaseModel):
    business_id: int
    shop_name: str
    slug: str
    owner_id: int
    owner_email: str
    access_token: str
    expires_at: datetime
    subscription: OnboardingSubscriptionOut
    provisioning_state: str = "pending"


class OnboardingProvisionOut(BaseModel):
    """Safe provisioning status; never contains tenant rows or credentials."""

    business_id: int
    schema_name: str
    state: str
    tenant_revision: str | None = None
    feature_enabled: bool


ChannelType = Literal["facebook", "instagram", "telegram", "zalo"]


class OnboardingChannelCreate(BaseModel):
    channel_type: ChannelType
    external_account_id: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    access_token: str = Field(..., min_length=1, max_length=10000)
    config: dict | None = None


class OnboardingChannelVerify(BaseModel):
    """A provider token submitted for one-time bot verification."""

    channel_type: Literal["telegram", "zalo"]
    access_token: str = Field(..., min_length=1, max_length=10000)


class OnboardingChannelVerifyOut(BaseModel):
    id: int
    business_id: int
    channel_type: str
    external_account_id: str
    name: str
    status: str
    connected_at: datetime | None = None
    provider_account: dict | None = None
    webhook_url: str
    webhook_status: str

    model_config = ConfigDict(from_attributes=True)


class OnboardingChannelStatusOut(BaseModel):
    id: int
    business_id: int
    channel_type: str
    external_account_id: str
    name: str
    status: str
    connected_at: datetime | None = None
    provider_account: dict | None = None
    webhook_url: str | None = None
    webhook_status: str = "unknown"

    model_config = ConfigDict(from_attributes=True)


class OnboardingChannelOut(BaseModel):
    id: int
    business_id: int
    channel_type: str
    external_account_id: str
    name: str
    status: str
    connected_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class OnboardingProductItem(BaseModel):
    sku: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    price: Decimal = Field(default=Decimal("0"), ge=0)
    stock_quantity: int = Field(default=0, ge=0)
    status: str = Field(default="active", min_length=1, max_length=30)
    metadata: dict | None = None


class OnboardingProductImport(BaseModel):
    items: list[OnboardingProductItem] = Field(..., min_length=1, max_length=5000)


class OnboardingProductImportOut(BaseModel):
    imported: int
    updated: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class QuotaResourceOut(BaseModel):
    used: int | float
    limit: int | float | None = None
    percent: float | None = None
    near_limit: bool
    exceeded: bool


class QuotaSnapshotOut(BaseModel):
    business_id: int
    period_start: datetime
    plan_code: str | None = None
    plan_name: str | None = None
    warning_percent: float
    resources: dict[str, QuotaResourceOut]
