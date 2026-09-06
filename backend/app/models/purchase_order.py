"""Purchase orders used when the business buys inventory or services."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("business_id", "po_number", name="uq_purchase_orders_business_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    po_number: Mapped[str] = mapped_column(String(60), nullable=False)
    supplier_name: Mapped[str] = mapped_column(String(255), nullable=False)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True, index=True)
    supplier_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    total_spend: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    payment_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unpaid", server_default="unpaid")
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0, server_default="0")
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    business = relationship("Business")
    supplier = relationship("Supplier", back_populates="purchase_orders")
    items = relationship("PurchaseOrderItem", back_populates="purchase_order", cascade="all, delete-orphan")
    receipts = relationship("PurchaseReceipt", back_populates="purchase_order", cascade="all, delete-orphan")
    payments = relationship("OrderPayment", back_populates="purchase_order", cascade="all, delete-orphan")


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    received_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    product_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sku_snapshot: Mapped[str | None] = mapped_column(String(80), nullable=True)

    purchase_order = relationship("PurchaseOrder", back_populates="items")
    product = relationship("Product")
    receipt_items = relationship("PurchaseReceiptItem", back_populates="purchase_order_item")
