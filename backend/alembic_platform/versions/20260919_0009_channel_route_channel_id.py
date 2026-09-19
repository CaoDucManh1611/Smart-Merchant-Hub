"""add tenant channel identity to webhook routes"""

from alembic import op
import sqlalchemy as sa


revision = "20260919_0009"
down_revision = "20260919_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("channel_routes")}
    if "channel_id" not in columns:
        op.add_column("channel_routes", sa.Column("channel_id", sa.Integer(), nullable=True))
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_channel_routes_channel_id "
            "ON channel_routes (channel_id)"
        )
    )
    bind.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_channel_route_provider_secret "
            "ON channel_routes (provider, secret_hash)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DROP INDEX IF EXISTS uq_channel_route_provider_secret"))
    bind.execute(sa.text("DROP INDEX IF EXISTS ix_channel_routes_channel_id"))
    columns = {column["name"] for column in sa.inspect(bind).get_columns("channel_routes")}
    if "channel_id" in columns:
        op.drop_column("channel_routes", "channel_id")
