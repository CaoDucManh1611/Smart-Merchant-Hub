"""Allow signup email verification before collecting shop details."""

from alembic import op
import sqlalchemy as sa


revision = "20261005_0056"
down_revision = "20260923_0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("signup_email_challenges") as batch_op:
        batch_op.alter_column("owner_name", existing_type=sa.String(length=255), nullable=True)
        batch_op.alter_column("shop_name", existing_type=sa.String(length=255), nullable=True)
        batch_op.alter_column("password_hash", existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    # Incomplete email-first challenges cannot be resumed after downgrading.
    op.execute(
        sa.text(
            "DELETE FROM signup_email_challenges "
            "WHERE owner_name IS NULL OR shop_name IS NULL OR password_hash IS NULL"
        )
    )
    with op.batch_alter_table("signup_email_challenges") as batch_op:
        batch_op.alter_column("owner_name", existing_type=sa.String(length=255), nullable=False)
        batch_op.alter_column("shop_name", existing_type=sa.String(length=255), nullable=False)
        batch_op.alter_column("password_hash", existing_type=sa.String(length=255), nullable=False)
