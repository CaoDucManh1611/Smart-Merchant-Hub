"""Add CRM attribution, lead activities and conversions."""

from alembic import op
import sqlalchemy as sa


revision = "20260907_0025"
down_revision = "20260906_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "revenue_touchpoints" not in tables:
        op.create_table(
            "revenue_touchpoints",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True),
            sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
            sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True),
            sa.Column("channel", sa.String(40), nullable=True),
            sa.Column("source", sa.String(120), nullable=False, server_default="conversation"),
            sa.Column("campaign", sa.String(160), nullable=True),
            sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_revenue_touchpoints_business_id", "revenue_touchpoints", ["business_id"])
        op.create_index("ix_revenue_touchpoints_customer_id", "revenue_touchpoints", ["customer_id"])
        op.create_index("ix_revenue_touchpoints_conversation_id", "revenue_touchpoints", ["conversation_id"])
        op.create_index("ix_revenue_touchpoints_lead_id", "revenue_touchpoints", ["lead_id"])
        op.create_index("ix_revenue_touchpoints_channel", "revenue_touchpoints", ["channel"])
        op.create_index("ix_revenue_touchpoints_campaign", "revenue_touchpoints", ["campaign"])
        op.create_index("ix_revenue_touchpoints_occurred_at", "revenue_touchpoints", ["occurred_at"])
    if "revenue_attributions" not in tables:
        op.create_table(
            "revenue_attributions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
            sa.Column("touchpoint_id", sa.Integer(), sa.ForeignKey("revenue_touchpoints.id", ondelete="CASCADE"), nullable=False),
            sa.Column("model", sa.String(30), nullable=False),
            sa.Column("weight", sa.Numeric(12, 8), nullable=False),
            sa.Column("amount", sa.Numeric(14, 2), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("business_id", "order_id", "touchpoint_id", "model", name="uq_revenue_attribution_allocation"),
        )
        op.create_index("ix_revenue_attributions_business_id", "revenue_attributions", ["business_id"])
        op.create_index("ix_revenue_attributions_order_id", "revenue_attributions", ["order_id"])
        op.create_index("ix_revenue_attributions_touchpoint_id", "revenue_attributions", ["touchpoint_id"])
        op.create_index("ix_revenue_attributions_model", "revenue_attributions", ["model"])
    if "lead_activities" not in tables:
        op.create_table(
            "lead_activities",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
            sa.Column("activity_type", sa.String(40), nullable=False),
            sa.Column("subject", sa.String(255), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_lead_activities_business_id", "lead_activities", ["business_id"])
        op.create_index("ix_lead_activities_lead_id", "lead_activities", ["lead_id"])
        op.create_index("ix_lead_activities_activity_type", "lead_activities", ["activity_type"])
        op.create_index("ix_lead_activities_occurred_at", "lead_activities", ["occurred_at"])
    if "lead_conversions" not in tables:
        op.create_table(
            "lead_conversions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
            sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
            sa.Column("converted_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("converted_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("business_id", "lead_id", name="uq_lead_conversion_lead"),
            sa.UniqueConstraint("business_id", "order_id", name="uq_lead_conversion_order"),
        )
        op.create_index("ix_lead_conversions_business_id", "lead_conversions", ["business_id"])
        op.create_index("ix_lead_conversions_lead_id", "lead_conversions", ["lead_id"])
        op.create_index("ix_lead_conversions_order_id", "lead_conversions", ["order_id"])


def downgrade() -> None:
    for table in ("lead_conversions", "lead_activities", "revenue_attributions", "revenue_touchpoints"):
        op.drop_table(table)
