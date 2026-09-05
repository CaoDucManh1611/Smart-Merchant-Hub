"""Add safe Customer 360 merge operations and saved segments."""

from alembic import op
import sqlalchemy as sa


revision = "20260905_0023"
down_revision = "20260904_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "customer_merge_operations" not in tables:
        op.create_table(
            "customer_merge_operations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("customer_merge_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="completed"),
            sa.Column("confidence_score", sa.Numeric(5, 4), nullable=True),
            sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("moved_records", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("confirmed_at", sa.DateTime(), nullable=True),
            sa.Column("undone_at", sa.DateTime(), nullable=True),
            sa.Column("undone_by", sa.Integer(), nullable=True),
            sa.Column("undo_reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["customer_merge_id"], ["customer_merges.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["undone_by"], ["users.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("customer_merge_id", name="uq_customer_merge_operations_merge"),
        )
        op.create_index("ix_customer_merge_operations_business_id", "customer_merge_operations", ["business_id"])
        op.create_index("ix_customer_merge_operations_customer_merge_id", "customer_merge_operations", ["customer_merge_id"])
        op.create_index("ix_customer_merge_operations_status", "customer_merge_operations", ["status"])

    if "customer_segments" not in tables:
        op.create_table(
            "customer_segments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("description", sa.String(length=2000), nullable=True),
            sa.Column("tag_ids", sa.JSON(), nullable=False),
            sa.Column("match_mode", sa.String(length=10), nullable=False, server_default="all"),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
            sa.UniqueConstraint("business_id", "name", name="uq_customer_segments_business_name"),
        )
        op.create_index("ix_customer_segments_business_id", "customer_segments", ["business_id"])
        op.create_index("ix_customer_segments_created_by", "customer_segments", ["created_by"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "customer_segments" in inspector.get_table_names():
        op.drop_index("ix_customer_segments_created_by", table_name="customer_segments")
        op.drop_index("ix_customer_segments_business_id", table_name="customer_segments")
        op.drop_table("customer_segments")
    if "customer_merge_operations" in inspector.get_table_names():
        op.drop_index("ix_customer_merge_operations_status", table_name="customer_merge_operations")
        op.drop_index("ix_customer_merge_operations_customer_merge_id", table_name="customer_merge_operations")
        op.drop_index("ix_customer_merge_operations_business_id", table_name="customer_merge_operations")
        op.drop_table("customer_merge_operations")
