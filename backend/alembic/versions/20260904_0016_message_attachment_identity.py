"""Allow a provider attachment id to be reused on different messages."""

from alembic import op
import sqlalchemy as sa


revision = "20260904_0016"
down_revision = "20260904_0015"
branch_labels = None
depends_on = None


OLD_INDEX = "uq_message_attachments_channel_external"
NEW_INDEX = "uq_message_attachments_message_external"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "message_attachments" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("message_attachments")}
    if OLD_INDEX in indexes:
        op.drop_index(OLD_INDEX, table_name="message_attachments")
    if NEW_INDEX in indexes:
        return
    bind = op.get_bind()
    kwargs = {}
    if bind.dialect.name == "postgresql":
        kwargs["postgresql_where"] = sa.text("external_attachment_id IS NOT NULL")
    else:
        kwargs["sqlite_where"] = sa.text("external_attachment_id IS NOT NULL")
    op.create_index(
        NEW_INDEX,
        "message_attachments",
        ["channel_id", "message_id", "external_attachment_id"],
        unique=True,
        **kwargs,
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "message_attachments" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("message_attachments")}
    if NEW_INDEX in indexes:
        op.drop_index(NEW_INDEX, table_name="message_attachments")
    if OLD_INDEX not in indexes:
        bind = op.get_bind()
        kwargs = {}
        if bind.dialect.name == "postgresql":
            kwargs["postgresql_where"] = sa.text("external_attachment_id IS NOT NULL")
        else:
            kwargs["sqlite_where"] = sa.text("external_attachment_id IS NOT NULL")
        op.create_index(
            OLD_INDEX,
            "message_attachments",
            ["channel_id", "external_attachment_id"],
            unique=True,
            **kwargs,
        )
