"""Allow explicit active and retryable provisioning-failed states."""

from alembic import op


revision = "20260915_0003"
down_revision = "20260915_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_tenant_registry_state", "tenant_registry", type_="check")
    op.create_check_constraint(
        "ck_tenant_registry_state",
        "tenant_registry",
        "state IN ('provisioning','active','provision_failed','disabled','ready','migrating','error')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tenant_registry_state", "tenant_registry", type_="check")
    op.create_check_constraint(
        "ck_tenant_registry_state",
        "tenant_registry",
        "state IN ('provisioning','ready','migrating','error','disabled')",
    )

