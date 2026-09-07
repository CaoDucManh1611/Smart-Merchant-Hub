"""Add auditable AI lifecycle and experiment measurement tables."""

from alembic import op
import sqlalchemy as sa


revision = "20260907_0028"
down_revision = "20260907_0027"
branch_labels = None
depends_on = None


def _columns(inspector, table):
    return {item["name"] for item in inspector.get_columns(table)} if table in inspector.get_table_names() else set()


def _add_column_if_missing(inspector, table, column):
    if column.name not in _columns(inspector, table):
        op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for name, column in (
        ("rule_suggestions", sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}")),
        ("rule_suggestions", sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default="[]")),
        ("rule_suggestions", sa.Column("source_event_ids", sa.JSON(), nullable=False, server_default="[]")),
        ("rule_suggestions", sa.Column("proposed_workflow_version", sa.String(40), nullable=True)),
        ("rule_suggestions", sa.Column("reviewer_note", sa.Text(), nullable=True)),
        ("rule_suggestions", sa.Column("converted_workflow_id", sa.Integer(), nullable=True)),
        ("rule_suggestions", sa.Column("converted_at", sa.DateTime(), nullable=True)),
        ("rule_suggestions", sa.Column("rolled_back_at", sa.DateTime(), nullable=True)),
        ("experiments", sa.Column("min_sample_size", sa.Integer(), nullable=False, server_default="0")),
        ("experiments", sa.Column("stop_criteria", sa.JSON(), nullable=False, server_default="{}")),
        ("experiments", sa.Column("stopped_at", sa.DateTime(), nullable=True)),
        ("experiment_outcomes", sa.Column("idempotency_key", sa.String(160), nullable=True)),
        ("bandit_decisions", sa.Column("policy_id", sa.Integer(), nullable=True)),
        ("bandit_decisions", sa.Column("policy_version", sa.String(40), nullable=True)),
        ("bandit_decisions", sa.Column("context_hash", sa.String(64), nullable=True)),
        ("bandit_decisions", sa.Column("selection_reason", sa.String(40), nullable=True)),
        ("bandit_decisions", sa.Column("idempotency_key", sa.String(160), nullable=True)),
        ("bandit_decisions", sa.Column("reward_idempotency_key", sa.String(160), nullable=True)),
    ):
        _add_column_if_missing(inspector, name, column)
        inspector = sa.inspect(bind)

    tables = set(inspector.get_table_names())
    if "experiment_exposures" not in tables:
        op.create_table(
            "experiment_exposures",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("experiment_id", sa.Integer(), nullable=False),
            sa.Column("assignment_id", sa.Integer(), nullable=True),
            sa.Column("subject_key", sa.String(255), nullable=False),
            sa.Column("variant", sa.String(80), nullable=False),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("exposed_at", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["assignment_id"], ["experiment_assignments.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("experiment_id", "idempotency_key", name="uq_experiment_exposure_idempotency"),
        )
        op.create_index("ix_experiment_exposures_business_id", "experiment_exposures", ["business_id"])
        op.create_index("ix_experiment_exposures_experiment_id", "experiment_exposures", ["experiment_id"])
        op.create_index("ix_experiment_exposures_assignment_id", "experiment_exposures", ["assignment_id"])
        op.create_index("ix_experiment_exposures_exposed_at", "experiment_exposures", ["exposed_at"])
    if "experiment_metric_aggregates" not in tables:
        op.create_table(
            "experiment_metric_aggregates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("experiment_id", sa.Integer(), nullable=False),
            sa.Column("metric", sa.String(80), nullable=False),
            sa.Column("variant", sa.String(80), nullable=False),
            sa.Column("exposure_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("outcome_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("value_sum", sa.Numeric(14, 4), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("experiment_id", "metric", "variant", name="uq_experiment_metric_variant"),
        )
        op.create_index("ix_experiment_metric_aggregates_business_id", "experiment_metric_aggregates", ["business_id"])
        op.create_index("ix_experiment_metric_aggregates_experiment_id", "experiment_metric_aggregates", ["experiment_id"])
    if "model_versions" not in tables:
        op.create_table(
            "model_versions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("version", sa.String(40), nullable=False),
            sa.Column("feature_version", sa.String(40), nullable=False),
            sa.Column("target", sa.String(120), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("artifact", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("trained_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("business_id", "name", "version", name="uq_model_version_business_name_version"),
        )
        op.create_index("ix_model_versions_business_id", "model_versions", ["business_id"])
        op.create_index("ix_model_versions_status", "model_versions", ["status"])
    if "model_training_runs" not in tables:
        op.create_table(
            "model_training_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("model_version_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="running"),
            sa.Column("snapshot_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("train_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("holdout_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("metrics", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("artifact", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["model_version_id"], ["model_versions.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_model_training_runs_business_id", "model_training_runs", ["business_id"])
        op.create_index("ix_model_training_runs_model_version_id", "model_training_runs", ["model_version_id"])
        op.create_index("ix_model_training_runs_status", "model_training_runs", ["status"])
    if "model_evaluation_metrics" not in tables:
        op.create_table(
            "model_evaluation_metrics",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("training_run_id", sa.Integer(), nullable=False),
            sa.Column("metric", sa.String(80), nullable=False),
            sa.Column("split", sa.String(30), nullable=False, server_default="holdout"),
            sa.Column("value", sa.Numeric(14, 6), nullable=False),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["training_run_id"], ["model_training_runs.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_model_evaluation_metrics_business_id", "model_evaluation_metrics", ["business_id"])
        op.create_index("ix_model_evaluation_metrics_training_run_id", "model_evaluation_metrics", ["training_run_id"])
    if "bandit_policies" not in tables:
        op.create_table(
            "bandit_policies",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("experiment_id", sa.Integer(), nullable=False),
            sa.Column("version", sa.String(40), nullable=False),
            sa.Column("epsilon", sa.Numeric(8, 6), nullable=False, server_default="0.10"),
            sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("experiment_id", "version", name="uq_bandit_policy_experiment_version"),
        )
        op.create_index("ix_bandit_policies_business_id", "bandit_policies", ["business_id"])
        op.create_index("ix_bandit_policies_experiment_id", "bandit_policies", ["experiment_id"])
        op.create_index("ix_bandit_policies_status", "bandit_policies", ["status"])
    if "bandit_arm_stats" not in tables:
        op.create_table(
            "bandit_arm_stats",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("policy_id", sa.Integer(), nullable=False),
            sa.Column("arm", sa.String(80), nullable=False),
            sa.Column("context_hash", sa.String(64), nullable=False),
            sa.Column("pulls", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reward_sum", sa.Numeric(14, 6), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["policy_id"], ["bandit_policies.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("policy_id", "arm", "context_hash", name="uq_bandit_arm_context"),
        )
        op.create_index("ix_bandit_arm_stats_business_id", "bandit_arm_stats", ["business_id"])
        op.create_index("ix_bandit_arm_stats_policy_id", "bandit_arm_stats", ["policy_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in ("bandit_arm_stats", "bandit_policies", "model_evaluation_metrics", "model_training_runs", "model_versions", "experiment_metric_aggregates", "experiment_exposures"):
        if table in inspector.get_table_names():
            op.drop_table(table)
    for table, columns in (
        ("bandit_decisions", ["reward_idempotency_key", "idempotency_key", "selection_reason", "context_hash", "policy_version", "policy_id"]),
        ("experiment_outcomes", ["idempotency_key"]),
        ("experiments", ["stopped_at", "stop_criteria", "min_sample_size"]),
        ("rule_suggestions", ["rolled_back_at", "converted_at", "converted_workflow_id", "reviewer_note", "proposed_workflow_version", "evidence_refs", "source_event_ids", "evidence"]),
    ):
        existing = _columns(sa.inspect(bind), table)
        for column in columns:
            if column in existing:
                op.drop_column(table, column)
