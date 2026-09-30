"""Add tenant-scoped message attachments."""

from alembic import op
import sqlalchemy as sa


revision = "20260904_0015"
down_revision = "20260904_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "message_attachments" in inspector.get_table_names():
        return

    op.create_table(
        "message_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=30), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=True),
        sa.Column("file_name", sa.String(length=500), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("external_attachment_id", sa.String(length=500), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_message_attachments_business_id", "message_attachments", ["business_id"])
    op.create_index("ix_message_attachments_message_id", "message_attachments", ["message_id"])
    op.create_index("ix_message_attachments_channel_id", "message_attachments", ["channel_id"])
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.create_index(
            "uq_message_attachments_channel_external",
            "message_attachments",
            ["channel_id", "external_attachment_id"],
            unique=True,
            postgresql_where=sa.text("external_attachment_id IS NOT NULL"),
        )
    else:
        # SQLite also supports partial indexes in the versions used by the
        # test suite; the fallback keeps local development migrations portable.
        op.create_index(
            "uq_message_attachments_channel_external",
            "message_attachments",
            ["channel_id", "external_attachment_id"],
            unique=True,
            sqlite_where=sa.text("external_attachment_id IS NOT NULL"),
        )


def downgrade() -> None:
    op.drop_index("uq_message_attachments_channel_external", table_name="message_attachments")
    op.drop_index("ix_message_attachments_channel_id", table_name="message_attachments")
    op.drop_index("ix_message_attachments_message_id", table_name="message_attachments")
    op.drop_index("ix_message_attachments_business_id", table_name="message_attachments")
    op.drop_table("message_attachments")
