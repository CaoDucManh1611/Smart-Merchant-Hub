"""Add the mirrored Enterprise tier with eight connection slots."""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0011"
down_revision = "20260922_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "INSERT INTO platform_service_plans "
        "(code, name, price, billing_cycle, quotas, features) VALUES "
        "('enterprise', 'Gói Enterprise', 1500000, 'monthly', "
        "'{\"staff_users\": 100, \"connected_channels\": 8, "
        "\"documents\": 500, \"rag_chunks\": 30000, "
        "\"ai_calls\": 75000, \"ai_cost\": 2500}'::json, "
        "'{\"onboarding\": true, \"support\": \"dedicated\", "
        "\"display_name\": \"Gói Enterprise\"}'::json) "
        "ON CONFLICT (code) DO UPDATE SET "
        "name = EXCLUDED.name, price = EXCLUDED.price, "
        "billing_cycle = EXCLUDED.billing_cycle, quotas = EXCLUDED.quotas, "
        "features = EXCLUDED.features"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "DELETE FROM platform_service_plans p WHERE p.code = 'enterprise' "
        "AND NOT EXISTS (SELECT 1 FROM platform_subscriptions s WHERE s.plan_id = p.id)"
    ))
