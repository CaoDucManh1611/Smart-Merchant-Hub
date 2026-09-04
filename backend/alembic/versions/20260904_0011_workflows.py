"""Add tenant-scoped workflow definitions and execution audit."""

from alembic import op
import sqlalchemy as sa


revision = "20260904_0011"
down_revision = "20260904_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if "workflows" not in tables:
        op.create_table(
            "workflows",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("event_type", sa.String(length=60), nullable=False),
            sa.Column("conditions", sa.JSON(), nullable=False),
            sa.Column("actions", sa.JSON(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_workflows_business_id", "workflows", ["business_id"])
        op.create_index("ix_workflows_event_type", "workflows", ["event_type"])
        op.create_index("ix_workflows_enabled", "workflows", ["enabled"])

    if "workflow_runs" not in tables:
        op.create_table(
            "workflow_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("workflow_id", sa.Integer(), nullable=False),
            sa.Column("event_id", sa.String(length=255), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False),
            sa.Column("matched", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("executed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("workflow_id", "event_id", name="uq_workflow_runs_event"),
        )
        op.create_index("ix_workflow_runs_business_id", "workflow_runs", ["business_id"])
        op.create_index("ix_workflow_runs_workflow_id", "workflow_runs", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_workflow_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_business_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_index("ix_workflows_enabled", table_name="workflows")
    op.drop_index("ix_workflows_event_type", table_name="workflows")
    op.drop_index("ix_workflows_business_id", table_name="workflows")
    op.drop_table("workflows")
