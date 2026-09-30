"""Remove the Enterprise tier from the customer-facing catalogue."""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0053"
down_revision = "20260922_0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep existing subscriptions and their audit history intact while
    # preventing new shops from selecting this retired catalogue item.
    op.execute(sa.text(
        "UPDATE service_plans SET status = 'archived' WHERE code = 'enterprise'"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE service_plans SET status = 'active' WHERE code = 'enterprise'"
    ))
