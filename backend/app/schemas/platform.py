"""Platform administration response contracts."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PlatformShopOut(BaseModel):
    id: int
    name: str
    slug: str
    status: str
    plan_code: str | None = None
    plan_name: str | None = None
    usage: dict[str, int | float] = Field(default_factory=dict)
    quota: dict = Field(default_factory=dict)
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
    quota: dict = Field(default_factory=dict)
    warnings: list[dict] = Field(default_factory=list)


class PlatformStatusOut(BaseModel):
    id: int
    status: str
    updated_at: datetime | None = None


class PlatformAuditOut(BaseModel):
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


class ProvisioningOut(BaseModel):
    business_id: int
    schema_name: str
    state: str
    feature_enabled: bool
    subscription_active: bool = False
    subscription_status: str | None = None
    tenant_revision: str | None = None
    migration_error: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ProvisioningRequest(BaseModel):
    idempotency_key: str = Field(..., min_length=8, max_length=180)


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

    @field_validator("features")
    @classmethod
    def validate_chatbot_rental_price(cls, value: dict | None) -> dict | None:
        """Keep the separately managed chatbot rental price JSON-safe."""

        if value is None:
            return None
        normalized = dict(value)
        raw_price = normalized.get("chatbot_rental_price")
        if raw_price is None:
            return normalized
        try:
            chatbot_price = Decimal(str(raw_price))
        except Exception as exc:  # Pydantic turns this into a useful 422 response.
            raise ValueError("Giá thuê trợ lý chatbot phải là một số không âm.") from exc
        if not chatbot_price.is_finite() or chatbot_price < 0:
            raise ValueError("Giá thuê trợ lý chatbot phải là một số không âm.")
        normalized["chatbot_rental_price"] = float(chatbot_price)
        return normalized


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

    @model_validator(mode="after")
    def validate_period(self):
        if self.starts_at is not None and self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("ends_at phải sau starts_at")
        return self


class PlatformSubscriptionOut(BaseModel):
    id: int
    business_id: int
    plan_id: int
    plan_code: str
    plan_name: str
    service_type: Literal["package", "chatbot"] = "package"
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


class PlatformPaymentOut(BaseModel):
    id: int
    business_id: int
    subscription_id: int
    amount: Decimal = Field(..., ge=0, max_digits=12, decimal_places=2)
    currency: str
    provider: str
    provider_transaction_id: str | None = None
    status: Literal["pending", "paid", "failed", "refunded"]
    paid_at: datetime | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PlatformSubscriptionRequestOut(BaseModel):
    """Minimal, platform-admin-only view of a pending package request."""

    subscription_id: int
    business_id: int
    shop_name: str
    shop_slug: str
    requester_name: str | None = None
    requester_email: str | None = None
    requested_at: datetime | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    requested_shop_name: str | None = None
    requested_channels: list[str] = Field(default_factory=list)
    request_notes: str | None = None
    owner_name: str | None = None
    owner_email: str | None = None
    plan_id: int
    plan_code: str
    plan_name: str
    service_type: Literal["package", "chatbot"] = "package"
    status: Literal["pending"] = "pending"
    created_at: datetime | None = None


class PlatformSubscriptionRequestListOut(BaseModel):
    items: list[PlatformSubscriptionRequestOut] = Field(default_factory=list)
    total: int = 0


class PlatformSubscriptionApprovalOut(BaseModel):
    subscription: PlatformSubscriptionOut
    provisioning: ProvisioningOut


class PlatformProviderErrorOut(BaseModel):
    id: int
    business_id: int
    channel_id: int | None = None
    channel_type: str | None = None
    event_type: str
    status: str
    error_type: str | None = None
    received_at: datetime | None = None


class PlatformPrivacyRequest(BaseModel):
    request_key: str = Field(..., min_length=8, max_length=180)
    confirmation_token: str | None = None


class PlatformPrivacyOut(BaseModel):
    id: int
    business_id: int
    kind: str
    status: str
    counts: dict[str, int] = Field(default_factory=dict)
