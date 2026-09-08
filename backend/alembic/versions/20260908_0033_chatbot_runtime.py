"""Add chatbot runtime controls and canned responses."""

from alembic import op
import sqlalchemy as sa


revision = "20260908_0033"
down_revision = "20260908_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "conversations" in tables and "bot_mode" not in {c["name"] for c in inspector.get_columns("conversations")}:
        op.add_column("conversations", sa.Column("bot_mode", sa.String(length=20), nullable=False, server_default="auto"))
    if "chatbot_configs" in tables and "business_hours" not in {c["name"] for c in inspector.get_columns("chatbot_configs")}:
        op.add_column("chatbot_configs", sa.Column("business_hours", sa.JSON(), nullable=True))
    if "canned_responses" not in tables:
        op.create_table(
            "canned_responses",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("shortcut", sa.String(length=40), nullable=False),
            sa.Column("title", sa.String(length=160), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint("business_id", "shortcut", name="uq_canned_responses_business_shortcut"),
        )
        op.create_index("ix_canned_responses_business_id", "canned_responses", ["business_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if "canned_responses" in sa.inspect(bind).get_table_names():
        op.drop_index("ix_canned_responses_business_id", table_name="canned_responses")
        op.drop_table("canned_responses")
    inspector = sa.inspect(bind)
    if "chatbot_configs" in inspector.get_table_names() and "business_hours" in {c["name"] for c in inspector.get_columns("chatbot_configs")}:
        op.drop_column("chatbot_configs", "business_hours")
    if "conversations" in inspector.get_table_names() and "bot_mode" in {c["name"] for c in inspector.get_columns("conversations")}:
        op.drop_column("conversations", "bot_mode")
