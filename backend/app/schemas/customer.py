"""Customer 360 API schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CustomerIdentityOut(BaseModel):
    id: int
    channel: str
    external_account_id: str
    external_user_id: str
    username: str | None = None
    display_name: str | None = None
    last_seen_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CustomerConversationOut(BaseModel):
    id: int
    channel: str
    status: str
    priority: str
    last_message_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CustomerListItem(BaseModel):
    id: int
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    channel: str
    updated_at: datetime | None = None
    conversation_count: int = 0


class CustomerListOut(BaseModel):
    items: list[CustomerListItem]
    total: int


class CustomerProfileOut(BaseModel):
    id: int
    business_id: int | None = None
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    avatar_url: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    identities: list[CustomerIdentityOut] = Field(default_factory=list)
    conversations: list[CustomerConversationOut] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    facts: list["CustomerFactOut"] = Field(default_factory=list)
    conversation_count: int = 0


class CustomerFactCreate(BaseModel):
    fact_type: str = Field(..., min_length=1, max_length=50)
    fact_key: str = Field(..., min_length=1, max_length=120)
    fact_value: Any
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_type: str = Field(default="manual", min_length=1, max_length=30)
    source_message_id: int | None = Field(default=None, ge=1)
    source_order_id: int | None = Field(default=None, ge=1)
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    extractor: str | None = Field(default=None, max_length=80)
    extractor_version: str | None = Field(default=None, max_length=40)
    is_verified: bool = False


class CustomerFactUpdate(BaseModel):
    fact_type: str | None = Field(default=None, min_length=1, max_length=50)
    fact_key: str | None = Field(default=None, min_length=1, max_length=120)
    fact_value: Any | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_type: str | None = Field(default=None, min_length=1, max_length=30)
    source_message_id: int | None = Field(default=None, ge=1)
    source_order_id: int | None = Field(default=None, ge=1)
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    extractor: str | None = Field(default=None, max_length=80)
    extractor_version: str | None = Field(default=None, max_length=40)
    is_verified: bool | None = None


class CustomerFactOut(BaseModel):
    id: int
    business_id: int
    customer_id: int
    fact_type: str
    fact_key: str
    fact_value: Any
    confidence: float
    source_type: str
    source_message_id: int | None = None
    source_order_id: int | None = None
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    extractor: str | None = None
    extractor_version: str | None = None
    is_verified: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CustomerFactListOut(BaseModel):
    items: list[CustomerFactOut]
    total: int


class CustomerFactExtractionStatusRequest(BaseModel):
    enabled: bool


class CustomerFactExtractionStatusOut(BaseModel):
    enabled: bool


class CustomerTagCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    color: str | None = Field(default=None, max_length=20)


class CustomerTagOut(BaseModel):
    id: int
    name: str
    color: str | None = None


class CustomerTagListOut(BaseModel):
    items: list[CustomerTagOut]
    total: int


class CustomerNoteCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)


class CustomerNoteOut(BaseModel):
    id: int
    customer_id: int
    content: str
    created_by: int | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CustomerTimelineItem(BaseModel):
    event_type: str
    event_id: int
    occurred_at: datetime | None = None
    channel: str | None = None
    direction: str | None = None
    content: str | None = None
    conversation_id: int | None = None
    created_by: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CustomerTimelineOut(BaseModel):
    items: list[CustomerTimelineItem]
    total: int
    offset: int = 0
    limit: int = 100
    has_more: bool = False
    next_offset: int | None = None
