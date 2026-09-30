"""Persist workflow event payloads and operational notifications."""

from alembic import op
import sqlalchemy as sa


revision = "20260904_0020"
down_revision = "20260904_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "workflow_runs" in inspector.get_table_names():
        columns = {item["name"] for item in inspector.get_columns("workflow_runs")}
        if "event_type" not in columns:
            op.add_column("workflow_runs", sa.Column("event_type", sa.String(60), nullable=True))
        if "payload" not in columns:
            op.add_column("workflow_runs", sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"))
        if "attempts" not in columns:
            op.add_column("workflow_runs", sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"))
        if "next_run_at" not in columns:
            op.add_column("workflow_runs", sa.Column("next_run_at", sa.DateTime(), nullable=True))
            op.create_index("ix_workflow_runs_next_run_at", "workflow_runs", ["next_run_at"])
    if "notifications" not in inspector.get_table_names():
        op.create_table(
            "notifications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_notifications_business_id", "notifications", ["business_id"])
        op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
        op.create_index("ix_notifications_kind", "notifications", ["kind"])
        op.create_index("ix_notifications_is_read", "notifications", ["is_read"])
        op.create_index("ix_notifications_created_at", "notifications", ["created_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "notifications" in inspector.get_table_names():
        for name in ("ix_notifications_created_at", "ix_notifications_is_read", "ix_notifications_kind", "ix_notifications_user_id", "ix_notifications_business_id"):
            op.drop_index(name, table_name="notifications")
        op.drop_table("notifications")
    if "workflow_runs" in inspector.get_table_names():
        columns = {item["name"] for item in inspector.get_columns("workflow_runs")}
        if "next_run_at" in columns:
            op.drop_index("ix_workflow_runs_next_run_at", table_name="workflow_runs")
            op.drop_column("workflow_runs", "next_run_at")
        for column in ("attempts", "payload", "event_type"):
            if column in columns:
                op.drop_column("workflow_runs", column)
