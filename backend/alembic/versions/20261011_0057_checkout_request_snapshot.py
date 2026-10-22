"""Freeze plan-change intent and price independently of catalogue changes."""
from alembic import op
import sqlalchemy as sa

revision = "20261011_0057"
down_revision = "20261005_0056"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    existing_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("subscriptions")
    }
    additions = (
        sa.Column("change_kind", sa.String(20), nullable=False, server_default="new"),
        sa.Column("previous_subscription_id", sa.Integer(), nullable=True),
        sa.Column("quoted_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("quoted_currency", sa.String(8), nullable=False, server_default="VND"),
    )
    missing = [column for column in additions if column.name not in existing_columns]
    if not missing:
        return
    with op.batch_alter_table("subscriptions") as batch:
        for column in missing:
            batch.add_column(column)

def downgrade():
    existing_columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("subscriptions")
    }
    with op.batch_alter_table("subscriptions") as batch:
        for column in ("quoted_currency", "quoted_amount", "previous_subscription_id", "change_kind"):
            if column in existing_columns:
                batch.drop_column(column)
