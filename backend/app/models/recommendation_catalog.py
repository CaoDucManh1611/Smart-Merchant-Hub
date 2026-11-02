"""Tenant-scoped catalog shared by RAG and recommendations."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String,
    Text, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.bases import TenantBase


class RecommendationCatalogEntry(TenantBase):
    """A product, service, rental, or other recommendable shop offer."""

    __tablename__ = "recommendation_catalog_entries"
    __table_args__ = (
        UniqueConstraint("business_id", "object_type", "external_id", name="uq_rce_business_type_external"),
        Index("ix_rce_shop_live", "business_id", "status", "availability"),
        Index("ix_rce_shop_type_live", "business_id", "object_type", "status", "availability"),
        Index("ix_rce_shop_sku", "business_id", "sku_norm"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(Integer, nullable=False)
    object_type: Mapped[str] = mapped_column(String(30), nullable=False)
    external_id: Mapped[str] = mapped_column(String(120), nullable=False)
    sku_norm: Mapped[str | None] = mapped_column(String(120), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    availability: Mapped[str] = mapped_column(String(30), nullable=False, default="in_stock")
    stock_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(String(60), nullable=False, default="catalog_sync")
    metadata_: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    attributes: Mapped[list["RecommendationCatalogAttribute"]] = relationship(back_populates="catalog_entry", cascade="all, delete-orphan")
    chunk_mappings: Mapped[list["RecommendationCatalogChunkMapping"]] = relationship(back_populates="catalog_entry", cascade="all, delete-orphan")


class RecommendationCatalogAttribute(TenantBase):
    """Normalized typed attribute; hard filters compare key/value exactly."""

    __tablename__ = "recommendation_catalog_attributes"
    __table_args__ = (
        UniqueConstraint("catalog_entry_id", "key_norm", "normalized_value", name="uq_rca_entry_key_value"),
        Index("ix_rca_exact_lookup", "key_norm", "normalized_value"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    catalog_entry_id: Mapped[int] = mapped_column(ForeignKey("recommendation_catalog_entries.id", ondelete="CASCADE"), nullable=False)
    key_norm: Mapped[str] = mapped_column(String(100), nullable=False)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False)
    normalized_value: Mapped[str] = mapped_column(String(255), nullable=False)
    text_value: Mapped[str | None] = mapped_column(Text)
    number_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    boolean_value: Mapped[bool | None] = mapped_column(Boolean)
    date_value: Mapped[date | None] = mapped_column(Date)
    catalog_entry: Mapped[RecommendationCatalogEntry] = relationship(back_populates="attributes")


class RecommendationCatalogChunkMapping(TenantBase):
    """Links an offer to RAG chunks so catalog constraints apply before LIMIT."""

    __tablename__ = "recommendation_catalog_chunk_mappings"
    __table_args__ = (
        UniqueConstraint("catalog_entry_id", "document_chunk_id", name="uq_rccm_entry_chunk"),
        Index("ix_rccm_chunk_entry", "document_chunk_id", "catalog_entry_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    catalog_entry_id: Mapped[int] = mapped_column(ForeignKey("recommendation_catalog_entries.id", ondelete="CASCADE"), nullable=False)
    document_chunk_id: Mapped[int] = mapped_column(ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False)
    mapping_type: Mapped[str] = mapped_column(String(30), nullable=False, default="primary")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    catalog_entry: Mapped[RecommendationCatalogEntry] = relationship(back_populates="chunk_mappings")
