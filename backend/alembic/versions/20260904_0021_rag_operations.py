"""Persist document embedding state and retained source bytes for reindex."""

from alembic import op
import sqlalchemy as sa


revision = "20260904_0021"
down_revision = "20260904_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "documents" not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns("documents")}
    if "embedding_status" not in columns:
        op.add_column("documents", sa.Column("embedding_status", sa.String(30), nullable=False, server_default="pending"))
        op.create_index("ix_documents_embedding_status", "documents", ["embedding_status"])
    if "reindex_count" not in columns:
        op.add_column("documents", sa.Column("reindex_count", sa.Integer(), nullable=False, server_default="0"))
    if "retry_after" not in columns:
        op.add_column("documents", sa.Column("retry_after", sa.DateTime(), nullable=True))
    if "source_bytes" not in columns:
        op.add_column("documents", sa.Column("source_bytes", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "documents" not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns("documents")}
    if "source_bytes" in columns:
        op.drop_column("documents", "source_bytes")
    if "retry_after" in columns:
        op.drop_column("documents", "retry_after")
    if "reindex_count" in columns:
        op.drop_column("documents", "reindex_count")
    if "embedding_status" in columns:
        op.drop_index("ix_documents_embedding_status", table_name="documents")
        op.drop_column("documents", "embedding_status")
