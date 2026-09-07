"""Add durable RAG run records."""

from alembic import op
import sqlalchemy as sa


revision = "20260907_0027"
down_revision = "20260907_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "rag_runs" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "rag_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False, server_default="ingestion"),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("phase", sa.String(30), nullable=True),
        sa.Column("provider", sa.String(80), nullable=True),
        sa.Column("source_document_ids", sa.JSON(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_rag_runs_business_id", "rag_runs", ["business_id"])
    op.create_index("ix_rag_runs_document_id", "rag_runs", ["document_id"])
    op.create_index("ix_rag_runs_status", "rag_runs", ["status"])


def downgrade() -> None:
    op.drop_table("rag_runs")
