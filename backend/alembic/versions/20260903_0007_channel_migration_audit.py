"""Record controlled legacy channel credential migration outcomes."""
from alembic import op
import sqlalchemy as sa


revision = "20260903_0007"
down_revision = "20260903_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "channel_migration_audits" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "channel_migration_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("channel_type", sa.String(length=30), nullable=False),
        sa.Column("external_account_id", sa.String(length=255), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"]),
    )


def downgrade() -> None:
    op.drop_table("channel_migration_audits")
