"""Add short-lived challenges for verified user email changes."""

from alembic import op
import sqlalchemy as sa


revision = "20260923_0055"
down_revision = "20260922_0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The metadata-driven baseline (or the legacy create_all startup path)
    # may have already created this model's table and indexes. Preserve those
    # rows and let Alembic record the revision instead of recreating the table.
    if sa.inspect(op.get_bind()).has_table("user_email_change_challenges"):
        return

    op.create_table(
        "user_email_change_challenges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("new_email", sa.String(length=255), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending_delivery"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_user_email_change_user_id", "user_email_change_challenges", ["user_id"])
    op.create_index("ix_user_email_change_business_id", "user_email_change_challenges", ["business_id"])
    op.create_index("ix_user_email_change_status", "user_email_change_challenges", ["status"])
    op.create_index("ix_user_email_change_user_status_created", "user_email_change_challenges", ["user_id", "status", "created_at"])
    op.create_index("ix_user_email_change_email_status", "user_email_change_challenges", ["new_email", "status"])


def downgrade() -> None:
    op.drop_index("ix_user_email_change_email_status", table_name="user_email_change_challenges")
    op.drop_index("ix_user_email_change_user_status_created", table_name="user_email_change_challenges")
    op.drop_index("ix_user_email_change_status", table_name="user_email_change_challenges")
    op.drop_index("ix_user_email_change_business_id", table_name="user_email_change_challenges")
    op.drop_index("ix_user_email_change_user_id", table_name="user_email_change_challenges")
    op.drop_table("user_email_change_challenges")
