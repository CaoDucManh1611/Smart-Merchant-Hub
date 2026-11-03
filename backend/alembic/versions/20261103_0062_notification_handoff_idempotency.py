"""Add a database uniqueness guard for idempotent staff notifications."""

from alembic import op
import sqlalchemy as sa


revision = "20261103_0062"
down_revision = "20261020_0061"
branch_labels = None
depends_on = None

_CONSTRAINT = "uq_notifications_business_kind_idempotency"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "notifications" not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns("notifications")}
    if "idempotency_key" not in columns:
        op.add_column("notifications", sa.Column("idempotency_key", sa.String(255), nullable=True))
    constraints = {item.get("name") for item in sa.inspect(bind).get_unique_constraints("notifications")}
    if _CONSTRAINT not in constraints:
        op.create_unique_constraint(
            _CONSTRAINT,
            "notifications",
            ["business_id", "kind", "idempotency_key"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "notifications" not in inspector.get_table_names():
        return
    constraints = {item.get("name") for item in inspector.get_unique_constraints("notifications")}
    if _CONSTRAINT in constraints:
        op.drop_constraint(_CONSTRAINT, "notifications", type_="unique")
    columns = {item["name"] for item in inspector.get_columns("notifications")}
    if "idempotency_key" in columns:
        op.drop_column("notifications", "idempotency_key")
