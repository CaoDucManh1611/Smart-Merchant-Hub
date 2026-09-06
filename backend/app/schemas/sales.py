"""Product and order API schemas."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProductCreate(BaseModel):
    sku: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    price: Decimal = Field(default=Decimal("0"), ge=0)
    stock_quantity: int = Field(default=0, ge=0)
    status: str = Field(default="active", min_length=1, max_length=30)
    metadata: dict | None = None


class ProductUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    price: Decimal | None = Field(default=None, ge=0)
    stock_quantity: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, min_length=1, max_length=30)
    metadata: dict | None = None


class ProductOut(BaseModel):
    id: int
    business_id: int
    sku: str
    name: str
    description: str | None = None
    price: Decimal
    stock_quantity: int
    reserved_quantity: int = 0
    status: str
    metadata: dict | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ProductListOut(BaseModel):
    items: list[ProductOut]
    total: int


class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int = Field(..., ge=1, le=100000)


class OrderCreate(BaseModel):
    order_number: str = Field(..., min_length=1, max_length=60)
    customer_id: int
    conversation_id: int | None = None
    items: list[OrderItemCreate] = Field(..., min_length=1)
    status: str = Field(default="draft", min_length=1, max_length=30)
    shipping_address: str | None = None
    shipping_phone: str | None = None
    metadata: dict | None = None


class OrderUpdate(BaseModel):
    status: str | None = Field(default=None, min_length=1, max_length=30)
    shipping_address: str | None = None
    shipping_phone: str | None = None
    metadata: dict | None = None


class OrderTransition(BaseModel):
    to_status: str = Field(..., min_length=1, max_length=30)


class OrderItemOut(BaseModel):
    id: int
    product_id: int
    product_name: str
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    product_name_snapshot: str | None = None
    sku_snapshot: str | None = None


class OrderOut(BaseModel):
    id: int
    business_id: int
    customer_id: int
    conversation_id: int | None = None
    channel: str | None = None
    order_number: str
    status: str
    total_amount: Decimal
    reserved_quantity: int = 0
    payment_status: str = "unpaid"
    paid_amount: Decimal = Decimal("0")
    refunded_amount: Decimal = Decimal("0")
    cancel_reason: str | None = None
    shipping_address: str | None = None
    shipping_phone: str | None = None
    metadata: dict | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime | None = None
    updated_at: datetime | None = None
    items: list[OrderItemOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class OrderListOut(BaseModel):
    items: list[OrderOut]
    total: int


class RevenueChannelItem(BaseModel):
    channel: str
    order_count: int
    revenue: Decimal


class RevenueByChannelOut(BaseModel):
    items: list[RevenueChannelItem]
    total_revenue: Decimal
