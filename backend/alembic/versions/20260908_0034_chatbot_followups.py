"""Add durable chatbot follow-up scheduling."""

from alembic import op
import sqlalchemy as sa


revision = "20260908_0034"
down_revision = "20260908_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "chatbot_followups" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "chatbot_followups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False, server_default="custom"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("run_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="scheduled"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.UniqueConstraint("business_id", "idempotency_key", name="uq_chatbot_followups_business_key"),
    )
    op.create_index("ix_chatbot_followups_business_id", "chatbot_followups", ["business_id"])
    op.create_index("ix_chatbot_followups_conversation_id", "chatbot_followups", ["conversation_id"])
    op.create_index("ix_chatbot_followups_customer_id", "chatbot_followups", ["customer_id"])
    op.create_index("ix_chatbot_followups_run_at", "chatbot_followups", ["run_at"])
    op.create_index("ix_chatbot_followups_status", "chatbot_followups", ["status"])


def downgrade() -> None:
    op.drop_index("ix_chatbot_followups_status", table_name="chatbot_followups")
    op.drop_index("ix_chatbot_followups_run_at", table_name="chatbot_followups")
    op.drop_index("ix_chatbot_followups_customer_id", table_name="chatbot_followups")
    op.drop_index("ix_chatbot_followups_conversation_id", table_name="chatbot_followups")
    op.drop_index("ix_chatbot_followups_business_id", table_name="chatbot_followups")
    op.drop_table("chatbot_followups")
