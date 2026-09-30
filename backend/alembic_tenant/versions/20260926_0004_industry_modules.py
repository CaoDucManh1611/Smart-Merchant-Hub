"""Add service appointments and B2B quotes, projects, and invoices.

Revision ID: 20260926_0004
Revises: 20260923_0003
"""

from alembic import context, op
import sqlalchemy as sa

from app.tenancy.schema import validate_schema_name


revision = "20260926_0004"
down_revision = "20260923_0003"
branch_labels = None
depends_on = None


def _schema() -> str:
    value = context.config.attributes.get("tenant_schema")
    if not value:
        value = context.get_x_argument(as_dictionary=True).get("tenant_schema")
    if not value:
        raise RuntimeError("tenant_schema Alembic attribute is required")
    return validate_schema_name(str(value))


def _create_index(table: str, columns: list[str], schema: str) -> None:
    op.create_index(f"ix_{table}_{columns[0]}", table, columns, schema=schema)


def upgrade() -> None:
    schema = _schema()
    existing = set(sa.inspect(op.get_bind()).get_table_names(schema=schema))
    if "appointment_services" not in existing:
        op.create_table(
            "appointment_services",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("price", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            schema=schema,
        )
        _create_index("appointment_services", ["business_id"], schema)

    if "appointments" not in existing:
        op.create_table(
            "appointments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey(f"{schema}.customers.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("service_id", sa.Integer(), sa.ForeignKey(f"{schema}.appointment_services.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("assigned_user_id", sa.Integer()),
            sa.Column("starts_at", sa.DateTime(), nullable=False),
            sa.Column("ends_at", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="scheduled"),
            sa.Column("notes", sa.Text()),
            sa.Column("reminder_minutes_before", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("reminder_at", sa.DateTime()),
            sa.Column("reminder_sent_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            schema=schema,
        )
        for column in ("business_id", "customer_id", "service_id", "starts_at", "status", "reminder_at", "assigned_user_id"):
            _create_index("appointments", [column], schema)

    if "commercial_quotes" not in existing:
        op.create_table(
            "commercial_quotes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey(f"{schema}.customers.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("quote_number", sa.String(40), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
            sa.Column("items", sa.JSON(), nullable=False),
            sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
            sa.Column("tax_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
            sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("valid_until", sa.Date()),
            sa.Column("notes", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("business_id", "quote_number", name="uq_quotes_business_number"),
            schema=schema,
        )
        for column in ("business_id", "customer_id", "status"):
            _create_index("commercial_quotes", [column], schema)

    if "commercial_projects" not in existing:
        op.create_table(
            "commercial_projects",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey(f"{schema}.customers.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("quote_id", sa.Integer(), sa.ForeignKey(f"{schema}.commercial_quotes.id", ondelete="SET NULL")),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="planned"),
            sa.Column("budget", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("starts_on", sa.Date()),
            sa.Column("due_on", sa.Date()),
            sa.Column("assigned_user_id", sa.Integer()),
            sa.Column("description", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("business_id", "quote_id", name="uq_projects_business_quote"),
            schema=schema,
        )
        for column in ("business_id", "customer_id", "quote_id", "status", "assigned_user_id"):
            _create_index("commercial_projects", [column], schema)

    if "commercial_invoices" not in existing:
        op.create_table(
            "commercial_invoices",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey(f"{schema}.customers.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey(f"{schema}.commercial_projects.id", ondelete="SET NULL")),
            sa.Column("quote_id", sa.Integer(), sa.ForeignKey(f"{schema}.commercial_quotes.id", ondelete="SET NULL")),
            sa.Column("invoice_number", sa.String(40), nullable=False),
            sa.Column("description", sa.String(240), nullable=False),
            sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("paid_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
            sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
            sa.Column("issued_on", sa.Date()),
            sa.Column("due_on", sa.Date()),
            sa.Column("notes", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("business_id", "invoice_number", name="uq_invoices_business_number"),
            schema=schema,
        )
        for column in ("business_id", "customer_id", "project_id", "quote_id", "status"):
            _create_index("commercial_invoices", [column], schema)

    if "commercial_invoice_payments" not in existing:
        op.create_table(
            "commercial_invoice_payments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("invoice_id", sa.Integer(), sa.ForeignKey(f"{schema}.commercial_invoices.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("amount", sa.Numeric(12, 2), nullable=False),
            sa.Column("paid_on", sa.Date(), nullable=False),
            sa.Column("method", sa.String(24), nullable=False, server_default="bank_transfer"),
            sa.Column("reference", sa.String(120)),
            sa.Column("notes", sa.Text()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            schema=schema,
        )
        for column in ("business_id", "invoice_id"):
            _create_index("commercial_invoice_payments", [column], schema)


def downgrade() -> None:
    schema = _schema()
    existing = set(sa.inspect(op.get_bind()).get_table_names(schema=schema))
    for table in ("commercial_invoice_payments", "commercial_invoices", "commercial_projects", "commercial_quotes", "appointments", "appointment_services"):
        if table in existing:
            op.drop_table(table, schema=schema)
