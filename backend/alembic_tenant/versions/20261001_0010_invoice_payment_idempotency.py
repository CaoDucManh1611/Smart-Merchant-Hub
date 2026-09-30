"""Make B2B invoice payment retries idempotent without rewriting old receipts."""

from alembic import context, op
import sqlalchemy as sa

from app.tenancy.schema import validate_schema_name


revision = "20261001_0010"
down_revision = "20260930_0009"
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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table = "commercial_invoice_payments"
    if table not in inspector.get_table_names(schema=schema):
        return
    columns = {column["name"] for column in inspector.get_columns(table, schema=schema)}
    if "idempotency_key" not in columns:
        op.add_column(table, sa.Column("idempotency_key", sa.String(160), nullable=True), schema=schema)
    constraints = {item.get("name") for item in sa.inspect(bind).get_unique_constraints(table, schema=schema)}
    if "uq_commercial_invoice_payments_business_key" not in constraints:
        op.create_unique_constraint(
            "uq_commercial_invoice_payments_business_key",
            table,
            ["business_id", "idempotency_key"],
            schema=schema,
        )


def downgrade() -> None:
    schema = _schema()
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table = "commercial_invoice_payments"
    if table not in inspector.get_table_names(schema=schema):
        return
    constraints = {item.get("name") for item in inspector.get_unique_constraints(table, schema=schema)}
    if "uq_commercial_invoice_payments_business_key" in constraints:
        op.drop_constraint("uq_commercial_invoice_payments_business_key", table, type_="unique", schema=schema)
    # Keep retry history on rollback; revision 0009 safely ignores this nullable column.
