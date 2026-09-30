"""Add shop-specific CRM fields and pipeline configuration."""

from alembic import context, op
import sqlalchemy as sa

from app.tenancy.schema import validate_schema_name


revision = "20260926_0005"
down_revision = "20260926_0004"
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
    tables = set(inspector.get_table_names(schema=schema))
    if "customers" in tables and "custom_fields" not in {column["name"] for column in inspector.get_columns("customers", schema=schema)}:
        op.add_column("customers", sa.Column("custom_fields", sa.JSON(), nullable=False, server_default=sa.text("'{}'")), schema=schema)
        op.alter_column("customers", "custom_fields", server_default=None, schema=schema)
    if "crm_workspace_configs" not in tables:
        op.create_table(
            "crm_workspace_configs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("customer_fields", sa.JSON(), nullable=False),
            sa.Column("pipeline_stages", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("business_id", name="uq_crm_workspace_configs_business"),
            schema=schema,
        )
        op.create_index("ix_crm_workspace_configs_business_id", "crm_workspace_configs", ["business_id"], schema=schema)


def downgrade() -> None:
    schema = _schema()
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names(schema=schema))
    if "crm_workspace_configs" in tables:
        op.drop_table("crm_workspace_configs", schema=schema)
    if "customers" in tables and "custom_fields" in {column["name"] for column in inspector.get_columns("customers", schema=schema)}:
        op.drop_column("customers", "custom_fields", schema=schema)
