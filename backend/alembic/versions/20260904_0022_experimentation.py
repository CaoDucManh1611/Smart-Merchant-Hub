"""Add explainable recommendations and experiment measurement tables."""

from alembic import op
import sqlalchemy as sa


revision = "20260904_0022"
down_revision = "20260904_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "rule_suggestions" not in tables:
        op.create_table("rule_suggestions",
            sa.Column("id", sa.Integer(), primary_key=True), sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("workflow_id", sa.Integer(), nullable=True), sa.Column("title", sa.String(255), nullable=False),
            sa.Column("rationale", sa.Text(), nullable=False), sa.Column("proposed_action", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"), sa.Column("reviewed_by", sa.Integer(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True), sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["workflow_id"], ["workflows.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"))
        op.create_index("ix_rule_suggestions_business_id", "rule_suggestions", ["business_id"]); op.create_index("ix_rule_suggestions_workflow_id", "rule_suggestions", ["workflow_id"]); op.create_index("ix_rule_suggestions_status", "rule_suggestions", ["status"])
    if "feature_snapshots" not in tables:
        op.create_table("feature_snapshots", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("business_id", sa.Integer(), nullable=False), sa.Column("customer_id", sa.Integer(), nullable=True), sa.Column("feature_version", sa.String(40), nullable=False), sa.Column("features", sa.JSON(), nullable=False), sa.Column("label", sa.JSON(), nullable=True), sa.Column("captured_at", sa.DateTime(), server_default=sa.func.now()), sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL")); op.create_index("ix_feature_snapshots_business_id", "feature_snapshots", ["business_id"]); op.create_index("ix_feature_snapshots_customer_id", "feature_snapshots", ["customer_id"]); op.create_index("ix_feature_snapshots_captured_at", "feature_snapshots", ["captured_at"])
    if "experiments" not in tables:
        op.create_table("experiments", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("business_id", sa.Integer(), nullable=False), sa.Column("name", sa.String(160), nullable=False), sa.Column("variants", sa.JSON(), nullable=False), sa.Column("status", sa.String(20), nullable=False, server_default="draft"), sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()), sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE")); op.create_index("ix_experiments_business_id", "experiments", ["business_id"]); op.create_index("ix_experiments_status", "experiments", ["status"])
    if "experiment_assignments" not in tables:
        op.create_table("experiment_assignments", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("business_id", sa.Integer(), nullable=False), sa.Column("experiment_id", sa.Integer(), nullable=False), sa.Column("subject_key", sa.String(255), nullable=False), sa.Column("variant", sa.String(80), nullable=False), sa.Column("assigned_at", sa.DateTime(), server_default=sa.func.now()), sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"], ondelete="CASCADE"), sa.UniqueConstraint("experiment_id", "subject_key", name="uq_experiment_assignment_subject")); op.create_index("ix_experiment_assignments_business_id", "experiment_assignments", ["business_id"]); op.create_index("ix_experiment_assignments_experiment_id", "experiment_assignments", ["experiment_id"])
    if "experiment_outcomes" not in tables:
        op.create_table("experiment_outcomes", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("business_id", sa.Integer(), nullable=False), sa.Column("assignment_id", sa.Integer(), nullable=False), sa.Column("metric", sa.String(80), nullable=False), sa.Column("value", sa.Numeric(14, 4), nullable=False), sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()), sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["assignment_id"], ["experiment_assignments.id"], ondelete="CASCADE")); op.create_index("ix_experiment_outcomes_business_id", "experiment_outcomes", ["business_id"]); op.create_index("ix_experiment_outcomes_assignment_id", "experiment_outcomes", ["assignment_id"])
    if "bandit_decisions" not in tables:
        op.create_table("bandit_decisions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("business_id", sa.Integer(), nullable=False), sa.Column("experiment_id", sa.Integer(), nullable=False), sa.Column("subject_key", sa.String(255), nullable=False), sa.Column("arm", sa.String(80), nullable=False), sa.Column("context", sa.JSON(), nullable=False), sa.Column("reward", sa.Numeric(14, 4), nullable=True), sa.Column("decided_at", sa.DateTime(), server_default=sa.func.now()), sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["experiment_id"], ["experiments.id"], ondelete="CASCADE")); op.create_index("ix_bandit_decisions_business_id", "bandit_decisions", ["business_id"]); op.create_index("ix_bandit_decisions_experiment_id", "bandit_decisions", ["experiment_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in ("bandit_decisions", "experiment_outcomes", "experiment_assignments", "experiments", "feature_snapshots", "rule_suggestions"):
        if table in inspector.get_table_names():
            op.drop_table(table)
