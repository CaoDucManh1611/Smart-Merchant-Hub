"""Add customer merge tracking and inactive source markers."""

from alembic import op
import sqlalchemy as sa


revision = "20260904_0017"
down_revision = "20260904_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("customers")}
    if "status" not in columns:
        op.add_column(
            "customers",
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        )
        op.create_index("ix_customers_status", "customers", ["status"])
    if "merged_into_customer_id" not in columns:
        op.add_column(
            "customers",
            sa.Column("merged_into_customer_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            "fk_customers_merged_into_customer",
            "customers",
            "customers",
            ["merged_into_customer_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(
            "ix_customers_merged_into_customer_id",
            "customers",
            ["merged_into_customer_id"],
        )
    if "customer_merges" not in inspector.get_table_names():
        op.create_table(
            "customer_merges",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("survivor_customer_id", sa.Integer(), nullable=False),
            sa.Column("source_customer_id", sa.Integer(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("before_counts", sa.JSON(), nullable=False),
            sa.Column("after_counts", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["survivor_customer_id"], ["customers.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["source_customer_id"], ["customers.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_customer_merges_business_id", "customer_merges", ["business_id"])
        op.create_index("ix_customer_merges_survivor_customer_id", "customer_merges", ["survivor_customer_id"])
        op.create_index("ix_customer_merges_source_customer_id", "customer_merges", ["source_customer_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "customer_merges" in inspector.get_table_names():
        op.drop_index("ix_customer_merges_source_customer_id", table_name="customer_merges")
        op.drop_index("ix_customer_merges_survivor_customer_id", table_name="customer_merges")
        op.drop_index("ix_customer_merges_business_id", table_name="customer_merges")
        op.drop_table("customer_merges")
    columns = {column["name"] for column in inspector.get_columns("customers")}
    if "merged_into_customer_id" in columns:
        op.drop_index("ix_customers_merged_into_customer_id", table_name="customers")
        op.drop_constraint("fk_customers_merged_into_customer", "customers", type_="foreignkey")
        op.drop_column("customers", "merged_into_customer_id")
    if "status" in columns:
        op.drop_index("ix_customers_status", table_name="customers")
        op.drop_column("customers", "status")
