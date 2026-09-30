"""Add unified audit event identity and actor metadata."""

from alembic import op
import sqlalchemy as sa


revision = "20260911_0038"
down_revision = "20260911_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("audit_logs")}
    additions = {
        "event_id": sa.Column("event_id", sa.String(length=64), nullable=True),
        "actor_type": sa.Column("actor_type", sa.String(length=20), nullable=False, server_default="system"),
        "correlation_id": sa.Column("correlation_id", sa.String(length=120), nullable=True),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column("audit_logs", column)
    if "event_id" not in columns:
        op.execute(sa.text("UPDATE audit_logs SET event_id = 'legacy-' || id WHERE event_id IS NULL"))
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("audit_logs") as batch:
                batch.alter_column("event_id", nullable=False)
        else:
            op.alter_column("audit_logs", "event_id", nullable=False)
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("audit_logs")}
    if "ix_audit_logs_event_id" not in indexes:
        op.create_index("ix_audit_logs_event_id", "audit_logs", ["event_id"], unique=True)
    if "ix_audit_logs_actor_type" not in indexes:
        op.create_index("ix_audit_logs_actor_type", "audit_logs", ["actor_type"])
    if "ix_audit_logs_correlation_id" not in indexes:
        op.create_index("ix_audit_logs_correlation_id", "audit_logs", ["correlation_id"])


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("audit_logs")}
    for name in ("ix_audit_logs_correlation_id", "ix_audit_logs_actor_type", "ix_audit_logs_event_id"):
        if name in indexes:
            op.drop_index(name, table_name="audit_logs")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("audit_logs")}
    for name in ("correlation_id", "actor_type", "event_id"):
        if name in columns:
            op.drop_column("audit_logs", name)
