"""Add supplier, inventory, receiving, payment and order event operations."""

from alembic import op
import sqlalchemy as sa


revision = "20260906_0024"
down_revision = "20260905_0023"
branch_labels = None
depends_on = None


def _columns(inspector, table_name: str) -> set[str]:
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _add_column_if_missing(inspector, table_name: str, column: sa.Column) -> None:
    if column.name not in _columns(inspector, table_name):
        op.add_column(table_name, column)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "suppliers" not in tables:
        op.create_table(
            "suppliers",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("code", sa.String(length=80), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("contact_name", sa.String(length=255), nullable=True),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("phone", sa.String(length=40), nullable=True),
            sa.Column("address", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("business_id", "code", name="uq_suppliers_business_code"),
        )
        op.create_index("ix_suppliers_business_id", "suppliers", ["business_id"])
        op.create_index("ix_suppliers_status", "suppliers", ["status"])

    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, "products", sa.Column("reserved_quantity", sa.Integer(), nullable=False, server_default="0"))
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, "orders", sa.Column("reserved_quantity", sa.Integer(), nullable=False, server_default="0"))
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, "orders", sa.Column("payment_status", sa.String(length=30), nullable=False, server_default="unpaid"))
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, "orders", sa.Column("paid_amount", sa.Numeric(14, 2), nullable=False, server_default="0"))
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, "orders", sa.Column("refunded_amount", sa.Numeric(14, 2), nullable=False, server_default="0"))
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, "orders", sa.Column("cancel_reason", sa.Text(), nullable=True))

    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, "order_items", sa.Column("product_name_snapshot", sa.String(length=255), nullable=True))
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, "order_items", sa.Column("sku_snapshot", sa.String(length=80), nullable=True))

    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, "purchase_orders", sa.Column("supplier_id", sa.Integer(), nullable=True))
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, "purchase_orders", sa.Column("supplier_name_snapshot", sa.String(length=255), nullable=True))
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, "purchase_orders", sa.Column("payment_status", sa.String(length=30), nullable=False, server_default="unpaid"))
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, "purchase_orders", sa.Column("paid_amount", sa.Numeric(14, 2), nullable=False, server_default="0"))
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, "purchase_orders", sa.Column("cancel_reason", sa.Text(), nullable=True))
    inspector = sa.inspect(bind)
    if "supplier_id" in _columns(inspector, "purchase_orders") and "suppliers" in inspector.get_table_names():
        existing_fks = {tuple(fk.get("constrained_columns", [])) for fk in inspector.get_foreign_keys("purchase_orders")}
        if ("supplier_id",) not in existing_fks:
            op.create_foreign_key(
                "fk_purchase_orders_supplier_id",
                "purchase_orders",
                "suppliers",
                ["supplier_id"],
                ["id"],
                ondelete="SET NULL",
            )
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, "purchase_order_items", sa.Column("received_quantity", sa.Integer(), nullable=False, server_default="0"))
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, "purchase_order_items", sa.Column("product_name_snapshot", sa.String(length=255), nullable=True))
    inspector = sa.inspect(bind)
    _add_column_if_missing(inspector, "purchase_order_items", sa.Column("sku_snapshot", sa.String(length=80), nullable=True))

    tables = set(sa.inspect(bind).get_table_names())
    if "stock_movements" not in tables:
        op.create_table(
            "stock_movements",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("movement_type", sa.String(length=40), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("quantity_before", sa.Integer(), nullable=False),
            sa.Column("quantity_after", sa.Integer(), nullable=False),
            sa.Column("source_type", sa.String(length=40), nullable=True),
            sa.Column("source_id", sa.Integer(), nullable=True),
            sa.Column("actor_id", sa.Integer(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_stock_movements_business_id", "stock_movements", ["business_id"])
        op.create_index("ix_stock_movements_product_id", "stock_movements", ["product_id"])
        op.create_index("ix_stock_movements_movement_type", "stock_movements", ["movement_type"])
        op.create_index("ix_stock_movements_created_at", "stock_movements", ["created_at"])

    tables = set(sa.inspect(bind).get_table_names())
    if "purchase_receipts" not in tables:
        op.create_table(
            "purchase_receipts",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("purchase_order_id", sa.Integer(), nullable=False),
            sa.Column("received_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("received_by", sa.Integer(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("idempotency_key", sa.String(length=160), nullable=False),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["received_by"], ["users.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("business_id", "idempotency_key", name="uq_purchase_receipts_business_idempotency"),
        )
        op.create_index("ix_purchase_receipts_business_id", "purchase_receipts", ["business_id"])
        op.create_index("ix_purchase_receipts_purchase_order_id", "purchase_receipts", ["purchase_order_id"])

    tables = set(sa.inspect(bind).get_table_names())
    if "purchase_receipt_items" not in tables:
        op.create_table(
            "purchase_receipt_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("receipt_id", sa.Integer(), nullable=False),
            sa.Column("purchase_order_item_id", sa.Integer(), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["receipt_id"], ["purchase_receipts.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["purchase_order_item_id"], ["purchase_order_items.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_purchase_receipt_items_receipt_id", "purchase_receipt_items", ["receipt_id"])
        op.create_index("ix_purchase_receipt_items_purchase_order_item_id", "purchase_receipt_items", ["purchase_order_item_id"])

    tables = set(sa.inspect(bind).get_table_names())
    if "order_payments" not in tables:
        op.create_table(
            "order_payments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("order_id", sa.Integer(), nullable=True),
            sa.Column("purchase_order_id", sa.Integer(), nullable=True),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("method", sa.String(length=40), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
            sa.Column("reference", sa.String(length=255), nullable=True),
            sa.Column("paid_at", sa.DateTime(), nullable=True),
            sa.Column("refunded_amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
            sa.Column("idempotency_key", sa.String(length=160), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("business_id", "idempotency_key", name="uq_order_payments_business_idempotency"),
        )
        op.create_index("ix_order_payments_business_id", "order_payments", ["business_id"])
        op.create_index("ix_order_payments_order_id", "order_payments", ["order_id"])
        op.create_index("ix_order_payments_purchase_order_id", "order_payments", ["purchase_order_id"])
        op.create_index("ix_order_payments_status", "order_payments", ["status"])

    tables = set(sa.inspect(bind).get_table_names())
    if "order_events" not in tables:
        op.create_table(
            "order_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("order_type", sa.String(length=30), nullable=False),
            sa.Column("order_id", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(length=50), nullable=False),
            sa.Column("from_status", sa.String(length=30), nullable=True),
            sa.Column("to_status", sa.String(length=30), nullable=True),
            sa.Column("actor_id", sa.Integer(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_order_events_business_id", "order_events", ["business_id"])
        op.create_index("ix_order_events_order_type", "order_events", ["order_type"])
        op.create_index("ix_order_events_order_id", "order_events", ["order_id"])
        op.create_index("ix_order_events_event_type", "order_events", ["event_type"])
        op.create_index("ix_order_events_created_at", "order_events", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table, indexes in (
        ("order_events", ["ix_order_events_created_at", "ix_order_events_event_type", "ix_order_events_order_id", "ix_order_events_order_type", "ix_order_events_business_id"]),
        ("order_payments", ["ix_order_payments_status", "ix_order_payments_purchase_order_id", "ix_order_payments_order_id", "ix_order_payments_business_id"]),
        ("purchase_receipt_items", ["ix_purchase_receipt_items_purchase_order_item_id", "ix_purchase_receipt_items_receipt_id"]),
        ("purchase_receipts", ["ix_purchase_receipts_purchase_order_id", "ix_purchase_receipts_business_id"]),
        ("stock_movements", ["ix_stock_movements_created_at", "ix_stock_movements_movement_type", "ix_stock_movements_product_id", "ix_stock_movements_business_id"]),
        ("suppliers", ["ix_suppliers_status", "ix_suppliers_business_id"]),
    ):
        if table in tables:
            for index in indexes:
                op.drop_index(index, table_name=table)
            op.drop_table(table)

    for table, columns in (
        ("purchase_order_items", ["sku_snapshot", "product_name_snapshot", "received_quantity"]),
        ("purchase_orders", ["cancel_reason", "paid_amount", "payment_status", "supplier_name_snapshot", "supplier_id"]),
        ("order_items", ["sku_snapshot", "product_name_snapshot"]),
        ("orders", ["cancel_reason", "refunded_amount", "paid_amount", "payment_status", "reserved_quantity"]),
        ("products", ["reserved_quantity"]),
    ):
        existing = _columns(sa.inspect(bind), table)
        for column in columns:
            if column in existing:
                op.drop_column(table, column)
