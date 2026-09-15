"""Append-only inventory movements and purchase receiving records."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.bases import TenantBase


class StockMovement(TenantBase):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    movement_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_before: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_after: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    product = relationship("Product")


class PurchaseReceipt(TenantBase):
    __tablename__ = "purchase_receipts"
    __table_args__ = (
        UniqueConstraint("business_id", "idempotency_key", name="uq_purchase_receipts_business_idempotency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    received_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)

    purchase_order = relationship("PurchaseOrder", back_populates="receipts")
    items = relationship("PurchaseReceiptItem", back_populates="receipt", cascade="all, delete-orphan")


class PurchaseReceiptItem(TenantBase):
    __tablename__ = "purchase_receipt_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("purchase_receipts.id", ondelete="CASCADE"), nullable=False, index=True)
    purchase_order_item_id: Mapped[int] = mapped_column(ForeignKey("purchase_order_items.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    receipt = relationship("PurchaseReceipt", back_populates="items")
    purchase_order_item = relationship("PurchaseOrderItem", back_populates="receipt_items")
