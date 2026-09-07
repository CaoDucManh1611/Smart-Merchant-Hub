"""Canonical metadata for Customer 360 tables backed by Core CRM migrations.

These two tables deliberately use SQLAlchemy Core: the merge and segment APIs
need dictionary-shaped rows, rather than ORM entities.  Keeping their metadata
in ``app.models`` makes Alembic's schema check include the tables and prevents
the runtime-only table declarations from drifting away from migrations.
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)

from app.database.session import Base


customer_merge_operations = Table(
    "customer_merge_operations",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("business_id", Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("customer_merge_id", Integer, ForeignKey("customer_merges.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("status", String(20), nullable=False, server_default="completed", index=True),
    Column("confidence_score", Numeric(5, 4), nullable=True),
    Column("evidence", JSON, nullable=False, server_default=text("'{}'")),
    Column("moved_records", JSON, nullable=False, server_default=text("'{}'")),
    Column("confirmed_at", DateTime, nullable=True),
    Column("undone_at", DateTime, nullable=True),
    Column("undone_by", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    Column("undo_reason", Text, nullable=True),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    UniqueConstraint("customer_merge_id", name="uq_customer_merge_operations_merge"),
)


customer_segments = Table(
    "customer_segments",
    Base.metadata,
    Column("id", Integer, primary_key=True),
    Column("business_id", Integer, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("name", String(160), nullable=False),
    Column("description", String(2000), nullable=True),
    Column("tag_ids", JSON, nullable=False),
    Column("match_mode", String(10), nullable=False, server_default="all"),
    Column("created_by", Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
    Column("created_at", DateTime, nullable=False, server_default=func.now()),
    Column("updated_at", DateTime, nullable=False, server_default=func.now()),
    UniqueConstraint("business_id", "name", name="uq_customer_segments_business_name"),
)
