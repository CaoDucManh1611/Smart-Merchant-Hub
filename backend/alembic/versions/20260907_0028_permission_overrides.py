"""Add tenant permission overrides."""

from alembic import op
import sqlalchemy as sa


revision = "20260907_0029"
down_revision = "20260907_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "permission_overrides" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "permission_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource", sa.String(80), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("effect", sa.String(10), nullable=False),
        sa.Column("role", sa.String(40), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("business_id", "resource", "action", "effect", "role", "user_id", name="uq_permission_override_scope"),
    )
    for name, column in (("business_id", "business_id"), ("resource", "resource"), ("action", "action"), ("role", "role"), ("user_id", "user_id")):
        op.create_index(f"ix_permission_overrides_{name}", "permission_overrides", [column])


def downgrade() -> None:
    op.drop_table("permission_overrides")
