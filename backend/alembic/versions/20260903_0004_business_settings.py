"""Add tenant-owned settings for per-business controls."""
from alembic import op
import sqlalchemy as sa


revision = "20260903_0004"
down_revision = "20260903_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "business_settings" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "business_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("business_id", "key", name="uq_business_settings_business_key"),
    )
    op.create_index("ix_business_settings_business_id", "business_settings", ["business_id"])


def downgrade() -> None:
    op.drop_index("ix_business_settings_business_id", table_name="business_settings")
    op.drop_table("business_settings")
