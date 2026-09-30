"""Supplier API schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SupplierCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = None
    status: str = Field(default="active", min_length=1, max_length=30)
    metadata: dict | None = None


class SupplierUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    address: str | None = None
    status: str | None = Field(default=None, min_length=1, max_length=30)
    metadata: dict | None = None


class SupplierOut(BaseModel):
    id: int
    business_id: int
    code: str
    name: str
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    status: str
    metadata: dict | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SupplierListOut(BaseModel):
    items: list[SupplierOut]
    total: int
