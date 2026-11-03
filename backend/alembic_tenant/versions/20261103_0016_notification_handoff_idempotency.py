"""Add a database uniqueness guard for idempotent staff notifications."""

from alembic import context, op
import sqlalchemy as sa

from app.tenancy.schema import validate_schema_name


revision = "20261103_0016"
down_revision = "20261101_0015"
branch_labels = None
depends_on = None

_CONSTRAINT = "uq_notifications_business_kind_idempotency"


def _schema() -> str:
    value = context.config.attributes.get("tenant_schema") or context.get_x_argument(as_dictionary=True).get("tenant_schema")
    if not value:
        raise RuntimeError("tenant_schema is required")
    return validate_schema_name(str(value))


def upgrade() -> None:
    schema = _schema()
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "notifications" not in inspector.get_table_names(schema=schema):
        return
    columns = {item["name"] for item in inspector.get_columns("notifications", schema=schema)}
    if "idempotency_key" not in columns:
        op.add_column(
            "notifications", sa.Column("idempotency_key", sa.String(255), nullable=True), schema=schema,
        )
    constraints = {
        item.get("name")
        for item in sa.inspect(bind).get_unique_constraints("notifications", schema=schema)
    }
    if _CONSTRAINT not in constraints:
        op.create_unique_constraint(
            _CONSTRAINT,
            "notifications",
            ["business_id", "kind", "idempotency_key"],
            schema=schema,
        )


def downgrade() -> None:
    schema = _schema()
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "notifications" not in inspector.get_table_names(schema=schema):
        return
    constraints = {
        item.get("name")
        for item in inspector.get_unique_constraints("notifications", schema=schema)
    }
    if _CONSTRAINT in constraints:
        op.drop_constraint(_CONSTRAINT, "notifications", type_="unique", schema=schema)
    columns = {item["name"] for item in inspector.get_columns("notifications", schema=schema)}
    if "idempotency_key" in columns:
        op.drop_column("notifications", "idempotency_key", schema=schema)
