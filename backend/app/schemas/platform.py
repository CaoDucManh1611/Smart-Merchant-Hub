"""Platform administration response contracts."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PlatformShopOut(BaseModel):
    id: int
    name: str
    slug: str
    status: str
    plan_code: str | None = None
    plan_name: str | None = None
    usage: dict[str, int | float] = Field(default_factory=dict)
    period_start: datetime


class PlatformShopListOut(BaseModel):
    items: list[PlatformShopOut]
    total: int


class PlatformStatusUpdate(BaseModel):
    status: Literal["active", "suspended"]


class PlatformUsageOut(BaseModel):
    business_id: int
    period_start: datetime
    plan_code: str | None = None
    limits: dict[str, int | float | None] = Field(default_factory=dict)
    usage: dict[str, int | float] = Field(default_factory=dict)


class PlatformStatusOut(BaseModel):
    id: int
    status: str
    updated_at: datetime | None = None


class PlatformAuditOut(BaseModel):
    id: int
    business_id: int
    user_id: int | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    metadata: dict = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TenantSchemaOut(BaseModel):
    id: int
    business_id: int
    schema_name: str
    state: Literal["proposed", "ready", "disabled"]
    feature_enabled: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TenantSchemaListOut(BaseModel):
    items: list[TenantSchemaOut]
    total: int


class TenantSchemaUpdate(BaseModel):
    state: Literal["proposed", "ready", "disabled"] | None = None
    feature_enabled: bool | None = None


class PlatformPlanCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=50, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    name: str = Field(..., min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    price: Decimal = Field(default=Decimal("0"), ge=0)
    billing_cycle: Literal["monthly", "yearly", "one_time"] = "monthly"
    max_users: int = Field(default=5, ge=0)
    max_channels: int = Field(default=2, ge=0)
    max_documents: int = Field(default=20, ge=0)
    max_rag_chunks: int = Field(default=500, ge=0)
    max_ai_calls: int = Field(default=1000, ge=0)
    max_ai_cost: Decimal = Field(default=Decimal("100"), ge=0)
    features: dict | None = None
    status: Literal["active", "archived"] = "active"


class PlatformPlanOut(PlatformPlanCreate):
    id: int
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PlatformSubscriptionUpdate(BaseModel):
    plan_id: int = Field(..., gt=0)
    status: Literal["pending", "active", "past_due", "cancelled", "expired"] = "active"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    auto_renew: bool = False


class PlatformSubscriptionOut(BaseModel):
    id: int
    business_id: int
    plan_id: int
    plan_code: str
    plan_name: str
    status: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    auto_renew: bool
    created_at: datetime | None = None


class PlatformPaymentCreate(BaseModel):
    subscription_id: int = Field(..., gt=0)
    amount: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="VND", min_length=3, max_length=8)
    provider: str = Field(..., min_length=2, max_length=40)
    provider_transaction_id: str = Field(..., min_length=1, max_length=255)
    status: Literal["pending", "paid", "failed", "refunded"] = "paid"
    paid_at: datetime | None = None


class PlatformPaymentOut(PlatformPaymentCreate):
    id: int
    business_id: int
    provider_transaction_id: str | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
