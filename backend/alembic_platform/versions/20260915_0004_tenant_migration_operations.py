"""Add content-free per-shop migration operation ledger."""

from alembic import op
import sqlalchemy as sa


revision = "20260915_0004"
down_revision = "20260915_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "tenant_migration_operations"
    index_name = "ix_tenant_migration_operations_business_id"

    if table_name not in inspector.get_table_names():
        op.create_table(
            table_name,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("operation_id", sa.String(length=64), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("state", sa.String(length=30), nullable=False),
            sa.Column("cursors", sa.JSON(), nullable=False),
            sa.Column("row_counts", sa.JSON(), nullable=False),
            sa.Column("checksums", sa.JSON(), nullable=False),
            sa.Column("error_code", sa.String(length=80), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=False),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["business_id"], ["platform_businesses.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("operation_id", name="uq_tenant_migration_operation_id"),
            sa.CheckConstraint(
                "state IN ('migrating','copied','verified','active','rolled_back','failed')",
                name="ck_tenant_migration_operation_state",
            ),
        )
        op.create_index(index_name, table_name, ["business_id"])
        return

    indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name not in indexes:
        op.create_index(index_name, table_name, ["business_id"])


def downgrade() -> None:
    op.drop_index("ix_tenant_migration_operations_business_id", table_name="tenant_migration_operations")
    op.drop_table("tenant_migration_operations")
