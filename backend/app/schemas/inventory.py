"""Inventory balance and movement API schemas."""

from datetime import datetime

from pydantic import BaseModel


class InventoryBalanceOut(BaseModel):
    product_id: int
    stock_quantity: int
    reserved_quantity: int
    available_quantity: int


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


class StockMovementListOut(BaseModel):
    items: list[StockMovementOut]
    total: int
