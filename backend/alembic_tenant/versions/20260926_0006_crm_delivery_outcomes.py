"""Track appointment opt-in and CRM email delivery."""

from alembic import context, op
import sqlalchemy as sa

from app.tenancy.schema import validate_schema_name


revision = "20260926_0006"
down_revision = "20260926_0005"
branch_labels = None
depends_on = None


def _schema() -> str:
    value = context.config.attributes.get("tenant_schema")
    if not value:
        value = context.get_x_argument(as_dictionary=True).get("tenant_schema")
    if not value:
        raise RuntimeError("tenant_schema Alembic attribute is required")
    return validate_schema_name(str(value))


def _add_if_missing(schema: str, table: str, column: sa.Column) -> None:
    inspector = sa.inspect(op.get_bind())
    if table in inspector.get_table_names(schema=schema):
        names = {item["name"] for item in inspector.get_columns(table, schema=schema)}
        if column.name not in names:
            op.add_column(table, column, schema=schema)


def upgrade() -> None:
    schema = _schema()
    _add_if_missing(schema, "appointments", sa.Column("send_customer_reminder", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    _add_if_missing(schema, "commercial_quotes", sa.Column("email_sent_at", sa.DateTime(), nullable=True))
    _add_if_missing(schema, "commercial_invoices", sa.Column("email_sent_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    schema = _schema()
    inspector = sa.inspect(op.get_bind())
    for table, name in (
        ("commercial_invoices", "email_sent_at"),
        ("commercial_quotes", "email_sent_at"),
        ("appointments", "send_customer_reminder"),
    ):
        if table in inspector.get_table_names(schema=schema):
            columns = {item["name"] for item in inspector.get_columns(table, schema=schema)}
            if name in columns:
                op.drop_column(table, name, schema=schema)
