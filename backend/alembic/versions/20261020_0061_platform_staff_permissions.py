"""Separate platform staff permissions from shop roles."""
from alembic import op
import sqlalchemy as sa

revision = '20261020_0061'
down_revision = '20261014_0060'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {
        column["name"] for column in inspector.get_columns("platform_memberships")
    }
    for column in (
        sa.Column("platform_role", sa.String(30), nullable=False, server_default="owner"),
        sa.Column("platform_permissions", sa.JSON(), nullable=True),
    ):
        if column.name not in existing_columns:
            op.add_column("platform_memberships", column)

    if not inspector.has_table("platform_staff_audit"):
        op.create_table(
            "platform_staff_audit",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("actor_id", sa.Integer(), nullable=False),
            sa.Column("subject_id", sa.Integer(), nullable=False),
            sa.Column("action", sa.String(40), nullable=False),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("platform_staff_audit"):
        op.drop_table("platform_staff_audit")

    existing_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("platform_memberships")
    }
    for column in ("platform_permissions", "platform_role"):
        if column in existing_columns:
            op.drop_column("platform_memberships", column)
