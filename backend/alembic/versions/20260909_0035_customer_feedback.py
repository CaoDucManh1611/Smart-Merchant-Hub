"""Add customer satisfaction feedback records."""

from alembic import op
import sqlalchemy as sa


revision = "20260909_0035"
down_revision = "20260908_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "customer_feedback" in inspector.get_table_names():
        return
    op.create_table(
        "customer_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("followup_id", sa.Integer(), sa.ForeignKey("chatbot_followups.id", ondelete="SET NULL"), nullable=True),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="scheduled"),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("requested_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("business_id", "idempotency_key", name="uq_customer_feedback_business_key"),
    )
    op.create_index("ix_customer_feedback_business_id", "customer_feedback", ["business_id"])
    op.create_index("ix_customer_feedback_conversation_id", "customer_feedback", ["conversation_id"])
    op.create_index("ix_customer_feedback_customer_id", "customer_feedback", ["customer_id"])
    op.create_index("ix_customer_feedback_ticket_id", "customer_feedback", ["ticket_id"])
    op.create_index("ix_customer_feedback_followup_id", "customer_feedback", ["followup_id"])
    op.create_index("ix_customer_feedback_status", "customer_feedback", ["status"])
    op.create_index("ix_customer_feedback_requested_at", "customer_feedback", ["requested_at"])


def downgrade() -> None:
    op.drop_index("ix_customer_feedback_requested_at", table_name="customer_feedback")
    op.drop_index("ix_customer_feedback_status", table_name="customer_feedback")
    op.drop_index("ix_customer_feedback_followup_id", table_name="customer_feedback")
    op.drop_index("ix_customer_feedback_ticket_id", table_name="customer_feedback")
    op.drop_index("ix_customer_feedback_customer_id", table_name="customer_feedback")
    op.drop_index("ix_customer_feedback_conversation_id", table_name="customer_feedback")
    op.drop_index("ix_customer_feedback_business_id", table_name="customer_feedback")
    op.drop_table("customer_feedback")
