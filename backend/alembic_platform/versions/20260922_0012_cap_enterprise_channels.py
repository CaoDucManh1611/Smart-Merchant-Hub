"""Cap the mirrored Enterprise quota at the six supported channels."""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0012"
down_revision = "20260922_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "UPDATE platform_service_plans SET quotas = jsonb_set(" 
        "COALESCE(quotas::jsonb, '{}'::jsonb), '{connected_channels}', "
        "'6'::jsonb, true)::json WHERE code = 'enterprise'"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE platform_service_plans SET quotas = jsonb_set(" 
        "COALESCE(quotas::jsonb, '{}'::jsonb), '{connected_channels}', "
        "'8'::jsonb, true)::json WHERE code = 'enterprise'"
    ))
