"""Add tenant-scoped sales leads and pipeline stages."""

from alembic import op
import sqlalchemy as sa


revision = "20260904_0009"
down_revision = "20260903_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "leads" in inspector.get_table_names():
        return
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("stage", sa.String(length=30), nullable=False, server_default="new"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="open"),
        sa.Column("value", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("probability", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_channel", sa.String(length=30), nullable=True),
        sa.Column("assigned_user_id", sa.Integer(), nullable=True),
        sa.Column("expected_close_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assigned_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    for name, column in (
        ("ix_leads_business_id", "business_id"),
        ("ix_leads_customer_id", "customer_id"),
        ("ix_leads_conversation_id", "conversation_id"),
        ("ix_leads_stage", "stage"),
        ("ix_leads_status", "status"),
        ("ix_leads_assigned_user_id", "assigned_user_id"),
    ):
        op.create_index(name, "leads", [column])


def downgrade() -> None:
    for name in (
        "ix_leads_assigned_user_id",
        "ix_leads_status",
        "ix_leads_stage",
        "ix_leads_conversation_id",
        "ix_leads_customer_id",
        "ix_leads_business_id",
    ):
        op.drop_index(name, table_name="leads")
    op.drop_table("leads")
