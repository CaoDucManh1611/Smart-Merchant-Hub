"""Expand the mirrored Premium CRM tier to all six supported channels."""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0010"
down_revision = "20260919_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "UPDATE platform_service_plans "
        "SET quotas = jsonb_set(COALESCE(quotas::jsonb, '{}'::jsonb), "
        "'{connected_channels}', '6'::jsonb, true)::json "
        "WHERE code = 'pro'"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE platform_service_plans "
        "SET quotas = jsonb_set(COALESCE(quotas::jsonb, '{}'::jsonb), "
        "'{connected_channels}', '4'::jsonb, true)::json "
        "WHERE code = 'pro'"
    ))
