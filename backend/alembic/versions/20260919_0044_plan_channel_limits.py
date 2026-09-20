"""Restore the customer plan channel quotas.

The previous demo migration temporarily made every tier four-channel. Keep
that migration immutable and correct the data with a forward migration.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260919_0044"
down_revision = "20260919_0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "UPDATE service_plans "
        "SET max_channels = CASE code "
        "WHEN 'starter' THEN 1 "
        "WHEN 'growth' THEN 2 "
        "WHEN 'pro' THEN 4 "
        "ELSE max_channels END "
        "WHERE code IN ('starter', 'growth', 'pro')"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE service_plans SET max_channels = 4 "
        "WHERE code IN ('starter', 'growth', 'pro')"
    ))

