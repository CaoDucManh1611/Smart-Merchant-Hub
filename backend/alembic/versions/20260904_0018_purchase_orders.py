"""Add tenant-scoped purchase orders."""

from alembic import op
import sqlalchemy as sa


revision = "20260904_0018"
down_revision = "20260904_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "purchase_orders" not in tables:
        op.create_table(
            "purchase_orders",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("po_number", sa.String(length=60), nullable=False),
            sa.Column("supplier_name", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
            sa.Column("total_spend", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("business_id", "po_number", name="uq_purchase_orders_business_number"),
        )
        op.create_index("ix_purchase_orders_business_id", "purchase_orders", ["business_id"])
        op.create_index("ix_purchase_orders_status", "purchase_orders", ["status"])
    if "purchase_order_items" not in tables:
        op.create_table(
            "purchase_order_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("purchase_order_id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("unit_cost", sa.Numeric(14, 2), nullable=False),
            sa.Column("line_total", sa.Numeric(14, 2), nullable=False),
            sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        )
        op.create_index("ix_purchase_order_items_purchase_order_id", "purchase_order_items", ["purchase_order_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "purchase_order_items" in inspector.get_table_names():
        op.drop_index("ix_purchase_order_items_purchase_order_id", table_name="purchase_order_items")
        op.drop_table("purchase_order_items")
    if "purchase_orders" in inspector.get_table_names():
        op.drop_index("ix_purchase_orders_status", table_name="purchase_orders")
        op.drop_index("ix_purchase_orders_business_id", table_name="purchase_orders")
        op.drop_table("purchase_orders")
