"""Add redacted provider incidents for metadata-only platform health."""

from alembic import op
import sqlalchemy as sa


revision = "20260915_0002"
down_revision = "20260915_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "platform_provider_incidents" not in inspector.get_table_names():
        op.create_table(
            "platform_provider_incidents",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("platform_businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("channel_id", sa.Integer(), nullable=True),
            sa.Column("channel_type", sa.String(length=30), nullable=True),
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("error_type", sa.String(length=40), nullable=True),
            sa.Column("received_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index("ix_platform_provider_incidents_business_id", "platform_provider_incidents", ["business_id"])


def downgrade() -> None:
    op.drop_index("ix_platform_provider_incidents_business_id", table_name="platform_provider_incidents")
    op.drop_table("platform_provider_incidents")
