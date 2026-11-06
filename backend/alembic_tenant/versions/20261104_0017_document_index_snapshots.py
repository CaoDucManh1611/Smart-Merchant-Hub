"""Add restorable document index snapshots for safe reindex rollback."""

from alembic import context, op
import sqlalchemy as sa

from app.tenancy.schema import validate_schema_name


revision = "20261104_0017"
down_revision = "20261103_0016"
branch_labels = None
depends_on = None


def _schema() -> str:
    value = context.config.attributes.get("tenant_schema") or context.get_x_argument(as_dictionary=True).get("tenant_schema")
    if not value:
        raise RuntimeError("tenant_schema is required")
    return validate_schema_name(str(value))


def upgrade() -> None:
    schema = _schema()
    if "document_index_snapshots" in sa.inspect(op.get_bind()).get_table_names(schema=schema):
        return
    op.create_table(
        "document_index_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(40), nullable=False, server_default="pre_publish"),
        sa.Column("document_state", sa.JSON(), nullable=False),
        sa.Column("chunks_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("restored_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], [f"{schema}.documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_id", "version", name="uq_document_index_snapshot_version"),
        schema=schema,
    )
    op.create_index("ix_document_index_snapshots_document_id", "document_index_snapshots", ["document_id"], schema=schema)
    op.create_index("ix_document_index_snapshots_business_id", "document_index_snapshots", ["business_id"], schema=schema)
    op.create_index(
        "ix_document_index_snapshots_tenant_document",
        "document_index_snapshots",
        ["business_id", "document_id", "created_at"],
        schema=schema,
    )


def downgrade() -> None:
    schema = _schema()
    if "document_index_snapshots" in sa.inspect(op.get_bind()).get_table_names(schema=schema):
        op.drop_table("document_index_snapshots", schema=schema)
