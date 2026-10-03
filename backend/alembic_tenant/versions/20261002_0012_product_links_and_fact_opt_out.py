"""Add product links and customer preference extraction opt-out."""

from alembic import context, op
import sqlalchemy as sa

from app.tenancy.schema import validate_schema_name


revision = "20261002_0012"
down_revision = "20261001_0011"
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
    if "products" in inspector.get_table_names(schema=schema):
        columns = {item["name"] for item in inspector.get_columns("products", schema=schema)}
        if "product_url" not in columns:
            op.add_column("products", sa.Column("product_url", sa.Text(), nullable=True), schema=schema)
    if "customers" in inspector.get_table_names(schema=schema):
        columns = {item["name"] for item in inspector.get_columns("customers", schema=schema)}
        if "fact_extraction_opt_out" not in columns:
            op.add_column(
                "customers",
                sa.Column("fact_extraction_opt_out", sa.Boolean(), nullable=False, server_default=sa.false()),
                schema=schema,
            )


def downgrade() -> None:
    # Keep the two additive fields when rolling application code back: product
    # links and explicit privacy choices are user data and must not be erased.
    pass
