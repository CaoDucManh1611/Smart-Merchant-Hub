"""Add tenant-scoped customer facts and provenance metadata."""

from alembic import op
import sqlalchemy as sa


revision = "20260904_0014"
down_revision = "20260904_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "customer_facts" in inspector.get_table_names():
        return
    op.create_table(
        "customer_facts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("fact_type", sa.String(length=50), nullable=False),
        sa.Column("fact_key", sa.String(length=120), nullable=False),
        sa.Column("fact_value_json", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("source_type", sa.String(length=30), nullable=False, server_default="manual"),
        sa.Column("source_message_id", sa.Integer(), nullable=True),
        sa.Column("source_order_id", sa.Integer(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("valid_from", sa.DateTime(), nullable=True),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.Column("extractor", sa.String(length=80), nullable=True),
        sa.Column("extractor_version", sa.String(length=40), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_order_id"], ["orders.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_customer_facts_business_id", "customer_facts", ["business_id"])
    op.create_index("ix_customer_facts_customer_id", "customer_facts", ["customer_id"])
    op.create_index("ix_customer_facts_fact_type", "customer_facts", ["fact_type"])
    op.create_index("ix_customer_facts_fact_key", "customer_facts", ["fact_key"])
    op.create_index("ix_customer_facts_source_message_id", "customer_facts", ["source_message_id"])
    op.create_index("ix_customer_facts_source_order_id", "customer_facts", ["source_order_id"])
    op.create_index("ix_customer_facts_is_verified", "customer_facts", ["is_verified"])


def downgrade() -> None:
    op.drop_index("ix_customer_facts_is_verified", table_name="customer_facts")
    op.drop_index("ix_customer_facts_source_order_id", table_name="customer_facts")
    op.drop_index("ix_customer_facts_source_message_id", table_name="customer_facts")
    op.drop_index("ix_customer_facts_fact_key", table_name="customer_facts")
    op.drop_index("ix_customer_facts_fact_type", table_name="customer_facts")
    op.drop_index("ix_customer_facts_customer_id", table_name="customer_facts")
    op.drop_index("ix_customer_facts_business_id", table_name="customer_facts")
    op.drop_table("customer_facts")
