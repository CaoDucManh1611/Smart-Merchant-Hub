"""Mirror the four-channel Scale tier and Premium price in platform quota."""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0014"
down_revision = "20260922_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "INSERT INTO platform_service_plans "
        "(code, name, price, billing_cycle, quotas, features) VALUES "
        "('scale', 'Gói Scale', 1000000, 'monthly', "
        "'{\"staff_users\": 25, \"connected_channels\": 4, "
        "\"documents\": 100, \"rag_chunks\": 5000, "
        "\"ai_calls\": 12000, \"ai_cost\": 500}'::json, "
        "'{\"onboarding\": true, \"support\": \"priority\", "
        "\"display_name\": \"Gói Scale\"}'::json) "
        "ON CONFLICT (code) DO UPDATE SET "
        "name = EXCLUDED.name, price = EXCLUDED.price, "
        "billing_cycle = EXCLUDED.billing_cycle, quotas = EXCLUDED.quotas, "
        "features = EXCLUDED.features"
    ))
    op.execute(sa.text(
        "UPDATE platform_service_plans SET price = 1500000, quotas = jsonb_set(" 
        "jsonb_set(COALESCE(quotas::jsonb, '{}'::jsonb), '{connected_channels}', "
        "'6'::jsonb, true), '{ai_cost}', '1500'::jsonb, true)::json "
        "WHERE code = 'pro'"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE platform_service_plans SET price = 1000000, quotas = jsonb_set(" 
        "COALESCE(quotas::jsonb, '{}'::jsonb), '{ai_cost}', '1000'::jsonb, true)::json "
        "WHERE code = 'pro'"
    ))
    op.execute(sa.text(
        "DELETE FROM platform_service_plans p WHERE p.code = 'scale' "
        "AND NOT EXISTS (SELECT 1 FROM platform_subscriptions s WHERE s.plan_id = p.id)"
    ))
