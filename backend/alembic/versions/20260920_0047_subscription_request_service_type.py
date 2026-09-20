"""Track the requested service on pending subscription approvals."""

from alembic import op
import sqlalchemy as sa


revision = "20260920_0047"
down_revision = "20260919_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column(
            "service_type",
            sa.String(length=20),
            nullable=False,
            server_default="package",
        ),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "service_type")

