"""Persist progress for background knowledge-base ingestion."""

from alembic import context, op
import sqlalchemy as sa

from app.tenancy.schema import validate_schema_name


revision = "20260921_0002"
down_revision = "20260915_0001"
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
    columns = {column["name"] for column in inspector.get_columns("rag_runs", schema=schema)}
    if "total_chunks" not in columns:
        op.add_column("rag_runs", sa.Column("total_chunks", sa.Integer(), nullable=False, server_default="0"), schema=schema)
    if "completed_chunks" not in columns:
        op.add_column("rag_runs", sa.Column("completed_chunks", sa.Integer(), nullable=False, server_default="0"), schema=schema)
    if "progress_percent" not in columns:
        op.add_column("rag_runs", sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"), schema=schema)


def downgrade() -> None:
    schema = _schema()
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("rag_runs", schema=schema)}
    for name in ("progress_percent", "completed_chunks", "total_chunks"):
        if name in columns:
            op.drop_column("rag_runs", name, schema=schema)
