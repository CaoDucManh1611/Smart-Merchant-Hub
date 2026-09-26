"""Store staff-confirmed conversation outcomes."""

from alembic import context, op
import sqlalchemy as sa

from app.tenancy.schema import validate_schema_name


revision = "20260926_0007"
down_revision = "20260926_0006"
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
    if "conversations" not in inspector.get_table_names(schema=schema):
        return
    columns = {column["name"] for column in inspector.get_columns("conversations", schema=schema)}
    if "resolution_outcome" not in columns:
        op.add_column("conversations", sa.Column("resolution_outcome", sa.String(length=32), nullable=True), schema=schema)


def downgrade() -> None:
    schema = _schema()
    inspector = sa.inspect(op.get_bind())
    if "conversations" in inspector.get_table_names(schema=schema):
        columns = {column["name"] for column in inspector.get_columns("conversations", schema=schema)}
        if "resolution_outcome" in columns:
            op.drop_column("conversations", "resolution_outcome", schema=schema)
