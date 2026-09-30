"""Expand the Premium CRM tier to all six supported channels."""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0050"
down_revision = "20260922_0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "UPDATE service_plans SET max_channels = 6 WHERE code = 'pro'"
    ))
    # Scale was the temporary three-channel tier. Keep historical
    # subscriptions intact, but stop offering it to new shops.
    op.execute(sa.text(
        "UPDATE service_plans SET status = 'archived' WHERE code = 'scale'"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE service_plans SET max_channels = 4 WHERE code = 'pro'"
    ))
    op.execute(sa.text(
        "UPDATE service_plans SET status = 'active' WHERE code = 'scale'"
    ))
