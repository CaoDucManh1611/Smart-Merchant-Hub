"""Complete P1 tenant context, usage warnings and PostgreSQL RLS guards."""

from alembic import op
import sqlalchemy as sa


revision = "20260913_0042"
down_revision = "20260912_0041"
branch_labels = None
depends_on = None


# Only tables with a first-class business_id are included.  Child tables such
# as messages/document_chunks inherit isolation through their parent queries;
# enabling a policy without a business_id column would be invalid SQL.
TENANT_TABLES = (
    "business_settings",
    "customers",
    "customer_identities",
    "customer_notes",
    "customer_facts",
    "customer_merges",
    "customer_contacts",
    "customer_addresses",
    "customer_collection_sessions",
    "customer_verification_challenges",
    "customer_consents",
    "customer_feedback",
    "conversations",
    "documents",
    "messages",
    "message_attachments",
    "channels",
    "channel_migration_audits",
    "audit_logs",
    "tags",
    "conversation_tags",
    "customer_tags",
    "conversation_assignments",
    "products",
    "orders",
    "order_events",
    "order_payments",
    "purchase_orders",
    "purchase_order_items",
    "suppliers",
    "stock_movements",
    "purchase_receipts",
    "purchase_receipt_items",
    "leads",
    "lead_activities",
    "lead_conversions",
    "tickets",
    "ticket_comments",
    "ticket_events",
    "workflows",
    "workflow_runs",
    "chatbot_configs",
    "canned_responses",
    "chatbot_followups",
    "revenue_touchpoints",
    "revenue_attributions",
    "lead_activity",
    "model_versions",
    "model_training_runs",
    "model_evaluation_metrics",
    "experiments",
    "experiment_assignments",
    "experiment_exposures",
    "experiment_outcomes",
    "experiment_metric_aggregates",
    "bandit_policies",
    "bandit_arm_stats",
    "bandit_decisions",
    "crm_jobs",
    "rag_runs",
    "permission_overrides",
    "saas_usage",
    "saas_quota_reservations",
    "data_lifecycle_requests",
    "tenant_schema_registry",
)


def _tables_with_business_id(bind) -> set[str]:
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    return {
        table
        for table in TENANT_TABLES
        if table in existing and any(column["name"] == "business_id" for column in inspector.get_columns(table))
    }


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in sorted(_tables_with_business_id(bind)):
        policy = f"p1_tenant_isolation_{table}"
        quoted_table = table.replace('"', '""')
        quoted_policy = policy.replace('"', '""')
        op.execute(sa.text(f'ALTER TABLE "{quoted_table}" ENABLE ROW LEVEL SECURITY'))
        # The DO block keeps this migration repeatable on databases where a
        # deployment already enabled the policy manually.
        op.execute(sa.text(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE schemaname = current_schema()
                      AND tablename = '{table}'
                      AND policyname = '{policy}'
                ) THEN
                    EXECUTE $policy$
                        CREATE POLICY "{quoted_policy}" ON "{quoted_table}"
                        USING (
                            current_setting('app.platform_admin', true) = 'true'
                            OR (
                                NULLIF(current_setting('app.business_id', true), '') IS NOT NULL
                                AND business_id = NULLIF(current_setting('app.business_id', true), '')::integer
                            )
                        )
                        WITH CHECK (
                            current_setting('app.platform_admin', true) = 'true'
                            OR (
                                NULLIF(current_setting('app.business_id', true), '') IS NOT NULL
                                AND business_id = NULLIF(current_setting('app.business_id', true), '')::integer
                            )
                        )
                    $policy$;
                END IF;
            END $$;
        """))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for table in sorted(_tables_with_business_id(bind)):
        policy = f"p1_tenant_isolation_{table}"
        op.execute(sa.text(f' DROP POLICY IF EXISTS "{policy}" ON "{table}"'))
