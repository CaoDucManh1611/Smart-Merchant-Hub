"""Add the zero-cost, no-channel platform quota plan."""

from alembic import op
import sqlalchemy as sa


revision = "20260919_0007"
down_revision = "20260919_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "INSERT INTO platform_service_plans "
        "(code, name, price, billing_cycle, quotas, features) VALUES "
        "('demo', 'Gói Demo', 0, 'monthly', "
        "'{\"staff_users\": 1, \"connected_channels\": 0, \"documents\": 0, "
        "\"rag_chunks\": 0, \"ai_calls\": 50, \"ai_cost\": 0}'::json, "
        "'{\"demo_only\": true}'::json) "
        "ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, price = EXCLUDED.price, "
        "quotas = EXCLUDED.quotas, features = EXCLUDED.features"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "DELETE FROM platform_service_plans p WHERE p.code = 'demo' "
        "AND NOT EXISTS (SELECT 1 FROM platform_subscriptions s WHERE s.plan_id = p.id)"
    ))
