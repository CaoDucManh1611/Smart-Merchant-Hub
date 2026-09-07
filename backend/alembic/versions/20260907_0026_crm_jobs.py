"""Add durable CRM job queue."""

from alembic import op
import sqlalchemy as sa


revision = "20260907_0026"
down_revision = "20260907_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "crm_jobs" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "crm_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("run_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("business_id", "idempotency_key", name="uq_crm_jobs_business_idempotency"),
    )
    op.create_index("ix_crm_jobs_business_id", "crm_jobs", ["business_id"])
    op.create_index("ix_crm_jobs_kind", "crm_jobs", ["kind"])
    op.create_index("ix_crm_jobs_status", "crm_jobs", ["status"])
    op.create_index("ix_crm_jobs_run_at", "crm_jobs", ["run_at"])


def downgrade() -> None:
    op.drop_table("crm_jobs")
