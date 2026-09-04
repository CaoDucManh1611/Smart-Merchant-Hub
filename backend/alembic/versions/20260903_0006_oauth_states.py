"""Persist OAuth nonces for atomic single-use replay protection."""
from alembic import op
import sqlalchemy as sa


revision = "20260903_0006"
down_revision = "20260903_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "oauth_states" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "oauth_states",
        sa.Column("nonce", sa.String(length=255), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("oauth_states")
