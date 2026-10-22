"""Freeze plan-change intent and price independently of catalogue changes."""
from alembic import op
import sqlalchemy as sa

revision = "20261011_0057"
down_revision = "20261005_0056"
branch_labels = None
depends_on = None

def upgrade():
    with op.batch_alter_table("subscriptions") as batch:
        batch.add_column(sa.Column("change_kind", sa.String(20), nullable=False, server_default="new"))
        batch.add_column(sa.Column("previous_subscription_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("quoted_amount", sa.Numeric(12, 2), nullable=True))
        batch.add_column(sa.Column("quoted_currency", sa.String(8), nullable=False, server_default="VND"))

def downgrade():
    with op.batch_alter_table("subscriptions") as batch:
        for column in ("quoted_currency", "quoted_amount", "previous_subscription_id", "change_kind"):
            batch.drop_column(column)
