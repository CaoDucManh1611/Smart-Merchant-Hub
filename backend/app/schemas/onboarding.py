"""Contracts for self-service tenant onboarding."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class OnboardingSubscriptionOut(BaseModel):
    id: int
    plan_code: str
    plan_name: str
    status: str


class OnboardingShopOut(BaseModel):
    business_id: int
    shop_name: str
    slug: str
    owner_id: int
    owner_email: str
    access_token: str
    expires_at: datetime
    subscription: OnboardingSubscriptionOut


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
