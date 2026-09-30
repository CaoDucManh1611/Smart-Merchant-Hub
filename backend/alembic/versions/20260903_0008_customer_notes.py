"""Add tenant-scoped customer notes for Customer 360 timeline."""

from alembic import op
import sqlalchemy as sa


revision = "20260903_0008"
down_revision = "20260903_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "customer_notes" in inspector.get_table_names():
        return
    op.create_table(
        "customer_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_customer_notes_business_id", "customer_notes", ["business_id"])
    op.create_index("ix_customer_notes_customer_id", "customer_notes", ["customer_id"])


def downgrade() -> None:
    op.drop_index("ix_customer_notes_customer_id", table_name="customer_notes")
    op.drop_index("ix_customer_notes_business_id", table_name="customer_notes")
    op.drop_table("customer_notes")
