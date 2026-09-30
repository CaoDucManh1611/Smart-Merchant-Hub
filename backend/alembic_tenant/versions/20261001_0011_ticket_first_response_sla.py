"""Track first-response deadlines separately from ticket resolution deadlines."""

from alembic import context, op
import sqlalchemy as sa

from app.tenancy.schema import validate_schema_name


revision = "20261001_0011"
down_revision = "20261001_0010"
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
    table = "tickets"
    if table not in inspector.get_table_names(schema=schema):
        return
    columns = {column["name"] for column in inspector.get_columns(table, schema=schema)}
    if "first_response_due_at" not in columns:
        op.add_column(table, sa.Column("first_response_due_at", sa.DateTime(), nullable=True), schema=schema)
    if "first_response_at" not in columns:
        op.add_column(table, sa.Column("first_response_at", sa.DateTime(), nullable=True), schema=schema)
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table, schema=schema)}
    if "ix_tickets_first_response_due_at" not in indexes:
        op.create_index("ix_tickets_first_response_due_at", table, ["first_response_due_at"], schema=schema)


def downgrade() -> None:
    schema = _schema()
    inspector = sa.inspect(op.get_bind())
    table = "tickets"
    if table not in inspector.get_table_names(schema=schema):
        return
    indexes = {item["name"] for item in inspector.get_indexes(table, schema=schema)}
    if "ix_tickets_first_response_due_at" in indexes:
        op.drop_index("ix_tickets_first_response_due_at", table_name=table, schema=schema)
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table, schema=schema)}
    for column in ("first_response_at", "first_response_due_at"):
        if column in columns:
            op.drop_column(table, column, schema=schema)
