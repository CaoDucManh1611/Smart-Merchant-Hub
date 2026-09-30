"""Add purpose and tenant fields for verified staff invitations."""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0049"
down_revision = "20260920_0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"]
        for column in inspector.get_columns("signup_email_challenges")
    }
    if "purpose" not in columns:
        op.add_column(
            "signup_email_challenges",
            sa.Column("purpose", sa.String(length=30), nullable=True, server_default="signup"),
        )
    if "business_id" not in columns:
        op.add_column(
            "signup_email_challenges",
            sa.Column("business_id", sa.Integer(), nullable=True),
        )
    if "role" not in columns:
        op.add_column(
            "signup_email_challenges",
            sa.Column("role", sa.String(length=30), nullable=True),
        )
    op.execute(
        "UPDATE signup_email_challenges SET purpose = 'signup' WHERE purpose IS NULL"
    )
    indexes = {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes("signup_email_challenges")
    }
    if "ix_signup_email_challenges_purpose" not in indexes:
        op.create_index(
            "ix_signup_email_challenges_purpose",
            "signup_email_challenges",
            ["purpose"],
        )
    if "ix_signup_email_challenges_business_id" not in indexes:
        op.create_index(
            "ix_signup_email_challenges_business_id",
            "signup_email_challenges",
            ["business_id"],
        )


def downgrade() -> None:
    op.drop_index("ix_signup_email_challenges_business_id", table_name="signup_email_challenges")
    op.drop_index("ix_signup_email_challenges_purpose", table_name="signup_email_challenges")
    op.drop_column("signup_email_challenges", "role")
    op.drop_column("signup_email_challenges", "business_id")
    op.drop_column("signup_email_challenges", "purpose")
