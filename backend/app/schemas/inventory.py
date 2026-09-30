"""Inventory balance and movement API schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class InventoryBalanceOut(BaseModel):
    product_id: int
    stock_quantity: int
    reserved_quantity: int
    available_quantity: int


class StockAdjustmentCreate(BaseModel):
    quantity: int = Field(..., ge=-1_000_000, le=1_000_000)
    note: str | None = Field(default=None, max_length=10_000)
    reason: str | None = Field(default=None, max_length=1_000)

    @property
    def effective_note(self) -> str | None:
        value = (self.reason or self.note or "").strip()
        return value or None


class StockMovementOut(BaseModel):
    id: int
    business_id: int
    product_id: int
    movement_type: str
    quantity: int
    quantity_before: int
    quantity_after: int
    source_type: str | None = None
    source_id: int | None = None
    actor_id: int | None = None
    note: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StockMovementListOut(BaseModel):
    items: list[StockMovementOut]
    total: int


class InventoryAdjustmentOut(BaseModel):
    movement: StockMovementOut
    balance: InventoryBalanceOut
