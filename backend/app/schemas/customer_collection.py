"""API contracts for collecting and verifying customer details."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ContactKind = Literal["email", "phone"]
VerificationStatus = Literal["unverified", "pending", "verified", "rejected"]


class CustomerContactCreate(BaseModel):
    kind: ContactKind
    value: str = Field(..., min_length=3, max_length=255)
    source: str = Field(default="manual", min_length=1, max_length=50)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_primary: bool = False


class CustomerContactUpdate(BaseModel):
    value: str | None = Field(default=None, min_length=3, max_length=255)
    source: str | None = Field(default=None, min_length=1, max_length=50)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    is_primary: bool | None = None
    verification_status: VerificationStatus | None = None


class CustomerContactOut(BaseModel):
    id: int
    customer_id: int
    kind: ContactKind
    masked_value: str
    verification_status: VerificationStatus
    source: str
    confidence: float
    is_primary: bool
    verified_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CustomerContactListOut(BaseModel):
    items: list[CustomerContactOut]
    total: int


class CustomerAddressCreate(BaseModel):
    recipient_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    address_line1: str = Field(..., min_length=1, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    ward: str | None = Field(default=None, max_length=120)
    district: str | None = Field(default=None, max_length=120)
    province: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str = Field(default="VN", min_length=2, max_length=80)
    source: str = Field(default="manual", min_length=1, max_length=50)
    is_default: bool = False


class CustomerAddressOut(CustomerAddressCreate):
    id: int
    customer_id: int
    verification_status: VerificationStatus
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CustomerAddressListOut(BaseModel):
    items: list[CustomerAddressOut]
    total: int


class CustomerCollectionSessionCreate(BaseModel):
    purpose: str = Field(default="order", min_length=1, max_length=40)
    required_fields: list[str] = Field(default_factory=list, max_length=30)
    source_channel: str | None = Field(default=None, max_length=30)
    conversation_id: int | None = Field(default=None, ge=1)


class CustomerCollectionSessionUpdate(BaseModel):
    collected_fields: dict = Field(default_factory=dict)
    current_field: str | None = Field(default=None, max_length=80)
    status: Literal["pending", "partial", "completed", "abandoned"] | None = None


class CustomerCollectionSessionOut(BaseModel):
    id: int
    customer_id: int
    conversation_id: int | None = None
    purpose: str
    required_fields: list[str]
    collected_fields: dict
    current_field: str | None = None
    status: Literal["pending", "partial", "completed", "abandoned"]
    source_channel: str | None = None
    started_at: datetime | None = None
    last_activity_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CustomerConsentCreate(BaseModel):
    purpose: str = Field(..., min_length=1, max_length=60)
    status: Literal["granted", "revoked"]
    source_channel: str | None = Field(default=None, max_length=30)
    policy_version: str | None = Field(default=None, max_length=40)
    evidence_message_id: int | None = Field(default=None, ge=1)


class CustomerConsentOut(BaseModel):
    id: int
    customer_id: int
    purpose: str
    status: Literal["granted", "revoked"]
    source_channel: str | None = None
    policy_version: str | None = None
    evidence_message_id: int | None = None
    granted_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CustomerConsentListOut(BaseModel):
    items: list[CustomerConsentOut]
    total: int


class VerificationChallengeCreate(BaseModel):
    channel: Literal["sms", "email"]


class VerificationChallengeOut(BaseModel):
    id: int
    contact_id: int
    channel: Literal["sms", "email"]
    status: Literal["queued", "sent", "verified", "expired", "locked"]
    attempts: int
    expires_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VerificationChallengeVerify(BaseModel):
    code: str = Field(..., min_length=4, max_length=12)


class VerificationResultOut(BaseModel):
    challenge_id: int
    contact_id: int
    verification_status: VerificationStatus
    verified_at: datetime | None = None
