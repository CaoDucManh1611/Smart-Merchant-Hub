"""Remove the unused Enterprise quota row when it has no subscriptions."""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0013"
down_revision = "20260922_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "DELETE FROM platform_service_plans p WHERE p.code = 'enterprise' "
        "AND NOT EXISTS (SELECT 1 FROM platform_subscriptions s WHERE s.plan_id = p.id)"
    ))


def downgrade() -> None:
    # The customer catalogue migration remains the source of truth. A
    # previously referenced platform row is recreated by subscription sync.
    pass
