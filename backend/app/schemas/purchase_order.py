"""Purchase order API contracts."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PurchaseOrderItemCreate(BaseModel):
    product_id: int = Field(..., ge=1)
    quantity: int = Field(..., ge=1, le=1_000_000)
    unit_cost: Decimal = Field(..., ge=0)


class PurchaseOrderCreate(BaseModel):
    po_number: str = Field(..., min_length=1, max_length=60)
    supplier_id: int | None = Field(default=None, ge=1)
    supplier_name: str | None = Field(default=None, min_length=1, max_length=255)
    items: list[PurchaseOrderItemCreate] = Field(..., min_length=1)
    status: str = Field(default="draft", min_length=1, max_length=30)
    notes: str | None = Field(default=None, max_length=10000)
    metadata: dict | None = None


class PurchaseOrderUpdate(BaseModel):
    supplier_id: int | None = Field(default=None, ge=1)
    supplier_name: str | None = Field(default=None, min_length=1, max_length=255)
    notes: str | None = Field(default=None, max_length=10000)
    metadata: dict | None = None


class PurchaseOrderTransition(BaseModel):
    to_status: str = Field(..., min_length=1, max_length=30)


class PurchaseOrderItemOut(BaseModel):
    id: int
    product_id: int
    product_name: str
    quantity: int
    received_quantity: int = 0
    unit_cost: Decimal
    line_total: Decimal
    product_name_snapshot: str | None = None
    sku_snapshot: str | None = None


class PurchaseOrderOut(BaseModel):
    id: int
    business_id: int
    po_number: str
    supplier_id: int | None = None
    supplier_name: str
    status: str
    total_spend: Decimal
    notes: str | None = None
    metadata: dict | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime | None = None
    updated_at: datetime | None = None
    items: list[PurchaseOrderItemOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PurchaseOrderListOut(BaseModel):
    items: list[PurchaseOrderOut]
    total: int
