"""Add an expiry timestamp for chatbot draft inventory reservations."""

from alembic import op
import sqlalchemy as sa


revision = "20260912_0041"
down_revision = "20260912_0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("orders")}
    if "reservation_expires_at" not in columns:
        op.add_column("orders", sa.Column("reservation_expires_at", sa.DateTime(), nullable=True))
    indexes = {index["name"] for index in inspector.get_indexes("orders")}
    if "ix_orders_reservation_expires_at" not in indexes:
        op.create_index("ix_orders_reservation_expires_at", "orders", ["reservation_expires_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("orders")}
    if "ix_orders_reservation_expires_at" in indexes:
        op.drop_index("ix_orders_reservation_expires_at", table_name="orders")
    columns = {column["name"] for column in inspector.get_columns("orders")}
    if "reservation_expires_at" in columns:
        op.drop_column("orders", "reservation_expires_at")
