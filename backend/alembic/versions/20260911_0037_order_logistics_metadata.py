"""Add tenant-scoped logistics metadata to sales orders."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260911_0037"
down_revision = "20260911_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("orders")}
    for name, column in (
        ("shipping_provider", sa.String(length=80)),
        ("tracking_code", sa.String(length=160)),
        ("shipping_status", sa.String(length=30)),
    ):
        if name not in columns:
            op.add_column("orders", sa.Column(name, column, nullable=True))


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("orders")}
    for name in ("shipping_status", "tracking_code", "shipping_provider"):
        if name in columns:
            op.drop_column("orders", name)
