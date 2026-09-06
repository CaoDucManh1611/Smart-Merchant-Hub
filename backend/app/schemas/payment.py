"""Payment, refund and order-event API contracts."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PaymentCreate(BaseModel):
    idempotency_key: str = Field(..., min_length=1, max_length=160)
    amount: Decimal = Field(..., gt=0, max_digits=14, decimal_places=2)
    method: str = Field(..., min_length=1, max_length=40)
    status: str = Field(default="paid", min_length=1, max_length=30)
    reference: str | None = Field(default=None, max_length=255)


class RefundCreate(BaseModel):
    idempotency_key: str = Field(..., min_length=1, max_length=160)
    amount: Decimal = Field(..., gt=0, max_digits=14, decimal_places=2)
    reason: str | None = Field(default=None, max_length=1000)


class PaymentOut(BaseModel):
    id: int
    business_id: int
    order_id: int | None = None
    purchase_order_id: int | None = None
    amount: Decimal
    method: str
    status: str
    reference: str | None = None
    paid_at: datetime | None = None
    refunded_amount: Decimal = Decimal("0")
    idempotency_key: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PaymentResult(BaseModel):
    payment: PaymentOut
    order: object


class SalesPaymentResult(BaseModel):
    payment: PaymentOut
    order: "OrderOut"


class PurchasePaymentResult(BaseModel):
    payment: PaymentOut
    order: "PurchaseOrderOut"


class PaymentListOut(BaseModel):
    items: list[PaymentOut]
    total: int


class OrderEventOut(BaseModel):
    id: int
    business_id: int
    order_type: str
    order_id: int
    event_type: str
    from_status: str | None = None
    to_status: str | None = None
    actor_id: int | None = None
    metadata: dict | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class OrderEventListOut(BaseModel):
    items: list[OrderEventOut]
    total: int


from app.schemas.purchase_order import PurchaseOrderOut
from app.schemas.sales import OrderOut

SalesPaymentResult.model_rebuild()
PurchasePaymentResult.model_rebuild()
