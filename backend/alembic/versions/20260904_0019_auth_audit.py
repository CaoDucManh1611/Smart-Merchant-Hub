"""Add persisted auth sessions and append-only audit logs."""

from alembic import op
import sqlalchemy as sa


revision = "20260904_0019"
down_revision = "20260904_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "auth_sessions" not in tables:
        op.create_table(
            "auth_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("token_hash", sa.String(length=128), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("token_hash"),
        )
        op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
        op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"])
        op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    if "audit_logs" not in tables:
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("action", sa.String(length=80), nullable=False),
            sa.Column("resource_type", sa.String(length=80), nullable=False),
            sa.Column("resource_id", sa.String(length=120), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_audit_logs_business_id", "audit_logs", ["business_id"])
        op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
        op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
        op.create_index("ix_audit_logs_resource_type", "audit_logs", ["resource_type"])
        op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "audit_logs" in inspector.get_table_names():
        for name in ("ix_audit_logs_created_at", "ix_audit_logs_resource_type", "ix_audit_logs_action", "ix_audit_logs_user_id", "ix_audit_logs_business_id"):
            op.drop_index(name, table_name="audit_logs")
        op.drop_table("audit_logs")
    if "auth_sessions" in inspector.get_table_names():
        for name in ("ix_auth_sessions_expires_at", "ix_auth_sessions_token_hash", "ix_auth_sessions_user_id"):
            op.drop_index(name, table_name="auth_sessions")
        op.drop_table("auth_sessions")
