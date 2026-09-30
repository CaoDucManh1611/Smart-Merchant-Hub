"""Store hashed, short-lived signup email challenges."""

from alembic import op
import sqlalchemy as sa


revision = "20260919_0045"
down_revision = "20260919_0044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signup_email_challenges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("owner_name", sa.String(length=255), nullable=False),
        sa.Column("shop_name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_signup_email_challenges_email", "signup_email_challenges", ["email"])
    op.create_index("ix_signup_email_challenges_status", "signup_email_challenges", ["status"])
    op.create_index("ix_signup_email_challenges_email_status", "signup_email_challenges", ["email", "status"])


def downgrade() -> None:
    op.drop_index("ix_signup_email_challenges_email_status", table_name="signup_email_challenges")
    op.drop_index("ix_signup_email_challenges_status", table_name="signup_email_challenges")
    op.drop_index("ix_signup_email_challenges_email", table_name="signup_email_challenges")
    op.drop_table("signup_email_challenges")
