"""Public service-advice knowledge, separate from tenant RAG."""
from alembic import op
import sqlalchemy as sa

revision = "20261020_0004_knowledge"
down_revision = "20261012_0003_support_channels"
branch_labels = None
depends_on = None


def upgrade():
    if "platform_knowledge_documents" not in sa.inspect(op.get_bind()).get_table_names():
        op.create_table(
            "platform_knowledge_documents",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("filename", sa.String(255), nullable=False),
            sa.Column("content_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("chunks", sa.JSON(), nullable=False),
            sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )


def downgrade():
    op.drop_table("platform_knowledge_documents")
