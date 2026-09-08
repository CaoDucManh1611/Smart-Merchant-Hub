"""Add indexes declared by the customer and purchase-order models."""

from alembic import op
import sqlalchemy as sa


revision = "20260907_0031"
down_revision = "20260907_0030"
branch_labels = None
depends_on = None


_INDEXES = (
    ("customers", "ix_customers_merged_into_customer_id", "merged_into_customer_id"),
    ("customers", "ix_customers_status", "status"),
    ("purchase_orders", "ix_purchase_orders_supplier_id", "supplier_id"),
)


def _has_index(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(item["name"] == name for item in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table, name, column in _INDEXES:
        if table in tables and not _has_index(inspector, table, name):
            op.create_index(name, table, [column])
            inspector = sa.inspect(bind)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table, name, _column in reversed(_INDEXES):
        if table in tables and _has_index(inspector, table, name):
            op.drop_index(name, table_name=table)
            inspector = sa.inspect(bind)
