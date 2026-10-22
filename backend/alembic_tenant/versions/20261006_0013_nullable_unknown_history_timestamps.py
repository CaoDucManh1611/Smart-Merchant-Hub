"""Allow imported messages to retain an unknown source timestamp."""

from alembic import context, op
import sqlalchemy as sa

from app.tenancy.schema import validate_schema_name


revision = "20261006_0013"
down_revision = "20261002_0012"
branch_labels = None
depends_on = None


def _schema() -> str:
    value = context.config.attributes.get("tenant_schema")
    if not value:
        value = context.get_x_argument(as_dictionary=True).get("tenant_schema")
    if not value:
        raise RuntimeError("tenant_schema Alembic attribute is required")
    return validate_schema_name(str(value))


def upgrade() -> None:
    schema = _schema()
    inspector = sa.inspect(op.get_bind())
    if "messages" not in inspector.get_table_names(schema=schema):
        return
    columns = {column["name"]: column for column in inspector.get_columns("messages", schema=schema)}
    received_at = columns.get("received_at")
    if received_at and not received_at.get("nullable", True):
        op.alter_column(
            "messages",
            "received_at",
            existing_type=sa.DateTime(),
            nullable=True,
            schema=schema,
        )


def downgrade() -> None:
    # Unknown source timestamps must not be rewritten into false import-time
    # values during downgrade. Keep the column nullable when rolling back.
    pass
