"""Allow every default platform plan to connect all supported channels."""

from alembic import op
import sqlalchemy as sa


revision = "20260919_0005"
down_revision = "20260915_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ``quotas`` is a JSON column (not JSONB), so cast only for the update
    # operation and cast back to preserve the existing column contract.
    op.execute(
        sa.text(
            "UPDATE platform_service_plans "
            "SET quotas = jsonb_set(" 
            "COALESCE(quotas::jsonb, '{}'::jsonb), "
            "'{connected_channels}', '4'::jsonb, true)::json "
            "WHERE code IN ('starter', 'growth', 'pro')"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE platform_service_plans "
            "SET quotas = jsonb_set(" 
            "COALESCE(quotas::jsonb, '{}'::jsonb), "
            "'{connected_channels}', "
            "CASE code WHEN 'starter' THEN '1'::jsonb "
            "WHEN 'growth' THEN '2'::jsonb ELSE '4'::jsonb END, true)::json "
            "WHERE code IN ('starter', 'growth', 'pro')"
        )
    )
