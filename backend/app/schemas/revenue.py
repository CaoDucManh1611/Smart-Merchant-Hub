from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class TouchpointCreate(BaseModel):
    customer_id: int | None = None
    conversation_id: int | None = None
    lead_id: int | None = None
    channel: str | None = Field(default=None, max_length=40)
    source: str = Field(default="conversation", min_length=1, max_length=120)
    campaign: str | None = Field(default=None, max_length=160)
    occurred_at: datetime | None = None
    metadata: dict | None = None


class TouchpointOut(BaseModel):
    id: int
    business_id: int
    customer_id: int | None = None
    conversation_id: int | None = None
    lead_id: int | None = None
    channel: str | None = None
    source: str
    campaign: str | None = None
    occurred_at: datetime | None = None
    metadata: dict | None = Field(default=None, validation_alias="metadata_")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class TouchpointListOut(BaseModel):
    items: list[TouchpointOut]
    total: int


class AttributionRequest(BaseModel):
    model: str = Field(default="last_touch", pattern="^(first_touch|last_touch|linear|time_decay|manual)$")


class AttributionItemOut(BaseModel):
    touchpoint_id: int
    source: str
    channel: str | None = None
    campaign: str | None = None
    weight: Decimal
    amount: Decimal


class AttributionOut(BaseModel):
    order_id: int
    model: str
    total_attributed: Decimal
    items: list[AttributionItemOut]


class LeadActivityCreate(BaseModel):
    activity_type: str = Field(..., min_length=1, max_length=40)
    subject: str = Field(..., min_length=1, max_length=255)
    body: str | None = None
    occurred_at: datetime | None = None
    metadata: dict | None = None


class LeadActivityOut(BaseModel):
    id: int
    business_id: int
    lead_id: int
    activity_type: str
    subject: str
    body: str | None = None
    occurred_at: datetime | None = None
    actor_id: int | None = None
    metadata: dict | None = Field(default=None, validation_alias="metadata_")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class LeadActivityListOut(BaseModel):
    items: list[LeadActivityOut]
    total: int


class LeadConversionCreate(BaseModel):
    order_id: int


class LeadConversionOut(BaseModel):
    id: int
    business_id: int
    lead_id: int
    order_id: int
    converted_by: int | None = None
    converted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
