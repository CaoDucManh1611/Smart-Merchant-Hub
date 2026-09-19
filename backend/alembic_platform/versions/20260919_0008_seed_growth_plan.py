"""Ensure the platform control plane has the two-channel VIP plan."""

from alembic import op
import sqlalchemy as sa


revision = "20260919_0008"
down_revision = "20260919_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Older control-plane databases were created before the public catalogue
    # was mirrored here, so the growth/VIP row can be absent even though the
    # tenant database has it.  Keep this migration additive and idempotent.
    op.execute(sa.text(
        "INSERT INTO platform_service_plans "
        "(code, name, price, billing_cycle, quotas, features) VALUES "
        "('growth', 'Gói VIP', 400000, 'monthly', "
        "'{\"staff_users\": 10, \"connected_channels\": 2, \"documents\": 50, "
        "\"rag_chunks\": 5000, \"ai_calls\": 5000, \"ai_cost\": 250}'::json, "
        "'{\"onboarding\": true, \"support\": \"priority\", \"display_name\": \"Gói VIP\"}'::json) "
        "ON CONFLICT (code) DO UPDATE SET "
        "name = EXCLUDED.name, price = EXCLUDED.price, billing_cycle = EXCLUDED.billing_cycle, "
        "quotas = EXCLUDED.quotas, features = EXCLUDED.features"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "DELETE FROM platform_service_plans p WHERE p.code = 'growth' "
        "AND NOT EXISTS (SELECT 1 FROM platform_subscriptions s WHERE s.plan_id = p.id)"
    ))
