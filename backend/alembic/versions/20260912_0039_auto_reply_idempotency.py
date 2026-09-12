"""Persist deterministic bot reply keys for inbound idempotency."""

from alembic import op
import sqlalchemy as sa


revision = "20260912_0039"
down_revision = "20260911_0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "messages" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("messages")}
    if "auto_reply_key" not in columns:
        op.add_column("messages", sa.Column("auto_reply_key", sa.String(length=255), nullable=True))
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("messages")}
    if "ix_messages_auto_reply_key" not in indexes:
        op.create_index("ix_messages_auto_reply_key", "messages", ["auto_reply_key"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "messages" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("messages")}
    if "ix_messages_auto_reply_key" in indexes:
        op.drop_index("ix_messages_auto_reply_key", table_name="messages")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("messages")}
    if "auto_reply_key" in columns:
        op.drop_column("messages", "auto_reply_key")
