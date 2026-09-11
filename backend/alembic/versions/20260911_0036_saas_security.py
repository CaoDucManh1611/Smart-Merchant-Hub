"""Add SaaS control-plane, usage, session metadata, and tenant schema registry."""

from alembic import op
import sqlalchemy as sa


revision = "20260911_0036"
down_revision = "20260909_0035"
branch_labels = None
depends_on = None


def _columns(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "saas_usage" not in tables:
        op.create_table(
            "saas_usage",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("resource", sa.String(length=40), nullable=False),
            sa.Column("period_start", sa.DateTime(), nullable=False),
            sa.Column("used", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint("business_id", "resource", "period_start", name="uq_saas_usage_business_resource_period"),
        )
        op.create_index("ix_saas_usage_business_id", "saas_usage", ["business_id"])
        op.create_index("ix_saas_usage_resource", "saas_usage", ["resource"])
        op.create_index("ix_saas_usage_period_start", "saas_usage", ["period_start"])

    if "saas_quota_reservations" not in tables:
        op.create_table(
            "saas_quota_reservations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("usage_id", sa.Integer(), sa.ForeignKey("saas_usage.id", ondelete="CASCADE"), nullable=False),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("resource", sa.String(length=40), nullable=False),
            sa.Column("idempotency_key", sa.String(length=180), nullable=False),
            sa.Column("amount", sa.Numeric(18, 4), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint("business_id", "idempotency_key", name="uq_saas_quota_reservation_key"),
        )
        op.create_index("ix_saas_quota_reservations_usage_id", "saas_quota_reservations", ["usage_id"])
        op.create_index("ix_saas_quota_reservations_business_id", "saas_quota_reservations", ["business_id"])

    if "platform_memberships" not in tables:
        op.create_table(
            "platform_memberships",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint("user_id", name="uq_platform_memberships_user"),
        )
        op.create_index("ix_platform_memberships_user_id", "platform_memberships", ["user_id"])

    if "data_lifecycle_requests" not in tables:
        op.create_table(
            "data_lifecycle_requests",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("request_key", sa.String(length=180), nullable=False),
            sa.Column("kind", sa.String(length=30), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
            sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("result_metadata", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("business_id", "request_key", name="uq_data_lifecycle_business_key"),
        )
        op.create_index("ix_data_lifecycle_requests_business_id", "data_lifecycle_requests", ["business_id"])
        op.create_index("ix_data_lifecycle_requests_status", "data_lifecycle_requests", ["status"])
        op.create_index("ix_data_lifecycle_requests_requested_by", "data_lifecycle_requests", ["requested_by"])

    if "tenant_schema_registry" not in tables:
        op.create_table(
            "tenant_schema_registry",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("schema_name", sa.String(length=120), nullable=False),
            sa.Column("state", sa.String(length=30), nullable=False, server_default="proposed"),
            sa.Column("feature_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint("business_id", name="uq_tenant_schema_business"),
            sa.UniqueConstraint("schema_name", name="uq_tenant_schema_name"),
        )
        op.create_index("ix_tenant_schema_registry_business_id", "tenant_schema_registry", ["business_id"])

    if "service_plans" in tables:
        columns = _columns(bind, "service_plans")
        if "max_rag_chunks" not in columns:
            op.add_column("service_plans", sa.Column("max_rag_chunks", sa.Integer(), nullable=False, server_default="500"))
        if "max_ai_calls" not in columns:
            op.add_column("service_plans", sa.Column("max_ai_calls", sa.Integer(), nullable=False, server_default="1000"))
        if "max_ai_cost" not in columns:
            op.add_column("service_plans", sa.Column("max_ai_cost", sa.Numeric(14, 2), nullable=False, server_default="100"))

    if "auth_sessions" in tables:
        columns = _columns(bind, "auth_sessions")
        additions = {
            "device_label": sa.Column("device_label", sa.String(length=120), nullable=True),
            "user_agent_hash": sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
            "ip_hash": sa.Column("ip_hash", sa.String(length=64), nullable=True),
            "last_seen_at": sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            "mfa_verified": sa.Column("mfa_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        }
        for name, column in additions.items():
            if name not in columns:
                op.add_column("auth_sessions", column)

    if "users" in tables:
        columns = _columns(bind, "users")
        additions = {
            "mfa_secret_encrypted": sa.Column("mfa_secret_encrypted", sa.Text(), nullable=True),
            "mfa_status": sa.Column("mfa_status", sa.String(length=20), nullable=False, server_default="disabled"),
            "mfa_prepared_at": sa.Column("mfa_prepared_at", sa.DateTime(), nullable=True),
        }
        for name, column in additions.items():
            if name not in columns:
                op.add_column("users", column)


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "auth_sessions" in tables:
        columns = _columns(bind, "auth_sessions")
        for name in ("mfa_verified", "last_seen_at", "ip_hash", "user_agent_hash", "device_label"):
            if name in columns:
                op.drop_column("auth_sessions", name)
    if "users" in tables:
        columns = _columns(bind, "users")
        for name in ("mfa_prepared_at", "mfa_status", "mfa_secret_encrypted"):
            if name in columns:
                op.drop_column("users", name)
    if "service_plans" in tables:
        columns = _columns(bind, "service_plans")
        for name in ("max_ai_cost", "max_ai_calls", "max_rag_chunks"):
            if name in columns:
                op.drop_column("service_plans", name)
    if "tenant_schema_registry" in tables:
        op.drop_index("ix_tenant_schema_registry_business_id", table_name="tenant_schema_registry")
        op.drop_table("tenant_schema_registry")
    if "data_lifecycle_requests" in tables:
        for index in ("ix_data_lifecycle_requests_requested_by", "ix_data_lifecycle_requests_status", "ix_data_lifecycle_requests_business_id"):
            op.drop_index(index, table_name="data_lifecycle_requests")
        op.drop_table("data_lifecycle_requests")
    if "platform_memberships" in tables:
        op.drop_index("ix_platform_memberships_user_id", table_name="platform_memberships")
        op.drop_table("platform_memberships")
    if "saas_quota_reservations" in tables:
        for index in ("ix_saas_quota_reservations_business_id", "ix_saas_quota_reservations_usage_id"):
            op.drop_index(index, table_name="saas_quota_reservations")
        op.drop_table("saas_quota_reservations")
    if "saas_usage" in tables:
        for index in ("ix_saas_usage_period_start", "ix_saas_usage_resource", "ix_saas_usage_business_id"):
            op.drop_index(index, table_name="saas_usage")
        op.drop_table("saas_usage")
