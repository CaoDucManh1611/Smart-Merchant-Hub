"""Persist idempotency state for outbound channel delivery."""

from alembic import context, op
import sqlalchemy as sa

from app.tenancy.schema import validate_schema_name


revision = "20260930_0009"
down_revision = "20260929_0008"
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
    table_name = "channel_outbound_attempts"
    if table_name not in inspector.get_table_names(schema=schema):
        op.create_table(
            table_name,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("channel_id", sa.Integer(), nullable=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("conversation_id", sa.Integer(), nullable=False),
            sa.Column("client_id", sa.String(length=160), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="processing"),
            sa.Column("error_code", sa.String(length=40), nullable=True),
            sa.Column("message_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["channel_id"], [f"{schema}.channels.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["conversation_id"], [f"{schema}.conversations.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("business_id", "client_id", name="uq_channel_outbound_attempts_client"),
            schema=schema,
        )

    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes(table_name, schema=schema)}
    if "ix_channel_outbound_attempts_business_id" not in indexes:
        op.create_index(
            "ix_channel_outbound_attempts_business_id",
            table_name,
            ["business_id"],
            schema=schema,
        )
    if "ix_channel_outbound_attempts_status" not in indexes:
        op.create_index(
            "ix_channel_outbound_attempts_status",
            table_name,
            ["status"],
            schema=schema,
        )


def downgrade() -> None:
    schema = _schema()
    if "channel_outbound_attempts" in sa.inspect(op.get_bind()).get_table_names(schema=schema):
        op.drop_table("channel_outbound_attempts", schema=schema)
