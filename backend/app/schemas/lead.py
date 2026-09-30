"""Lead and sales pipeline API schemas."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


PIPELINE_STAGES = ("new", "qualified", "proposal", "won", "lost")


class LeadCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    customer_id: int
    conversation_id: int | None = None
    stage: str = Field(default="new", min_length=1, max_length=30)
    status: str = Field(default="open", min_length=1, max_length=30)
    value: Decimal = Field(default=Decimal("0"), ge=0)
    probability: int = Field(default=0, ge=0, le=100)
    source_channel: str | None = Field(default=None, max_length=30)
    assigned_user_id: int | None = None
    expected_close_at: datetime | None = None
    notes: str | None = None
    metadata: dict | None = None


class LeadUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    customer_id: int | None = None
    conversation_id: int | None = None
    stage: str | None = Field(default=None, min_length=1, max_length=30)
    status: str | None = Field(default=None, min_length=1, max_length=30)
    value: Decimal | None = Field(default=None, ge=0)
    probability: int | None = Field(default=None, ge=0, le=100)
    source_channel: str | None = Field(default=None, max_length=30)
    assigned_user_id: int | None = None
    expected_close_at: datetime | None = None
    notes: str | None = None
    metadata: dict | None = None


class LeadOut(BaseModel):
    id: int
    business_id: int
    customer_id: int
    conversation_id: int | None = None
    title: str
    stage: str
    status: str
    value: Decimal
    probability: int
    source_channel: str | None = None
    assigned_user_id: int | None = None
    expected_close_at: datetime | None = None
    notes: str | None = None
    metadata: dict | None = Field(default=None, validation_alias="metadata_")
    customer_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class LeadListOut(BaseModel):
    items: list[LeadOut]
    total: int


class PipelineStageItem(BaseModel):
    stage: str
    lead_count: int
    value: Decimal


class PipelineReportOut(BaseModel):
    items: list[PipelineStageItem]
    total_leads: int
    total_value: Decimal


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
