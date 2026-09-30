"""Bring the migrated schema back in sync with the application metadata.

This migration only adds missing constraints/indexes and makes timestamp fields
non-null after safely backfilling legacy nulls.  It never drops application
data.  Customer 360 Core tables are represented in ``app.models`` so Alembic
can now validate them as part of the normal schema check.
"""

from alembic import op
import sqlalchemy as sa

from app.core.config import settings


revision = "20260907_0030"
down_revision = "20260907_0029"
branch_labels = None
depends_on = None


def _has_index(inspector, table: str, name: str) -> bool:
    return any(item["name"] == name for item in inspector.get_indexes(table))


def _has_foreign_key(inspector, table: str, column: str, target_table: str) -> bool:
    return any(
        fk.get("referred_table") == target_table and column in fk.get("constrained_columns", [])
        for fk in inspector.get_foreign_keys(table)
    )


def _make_timestamp_required(bind, table: str, column: str) -> None:
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return
    metadata = {item["name"]: item for item in inspector.get_columns(table)}
    if column not in metadata or not metadata[column]["nullable"]:
        return

    # A legacy nullable value means the original timestamp is unavailable.
    # Preserve the row and record the migration time rather than deleting it.
    op.execute(sa.text(f"UPDATE {table} SET {column} = CURRENT_TIMESTAMP WHERE {column} IS NULL"))
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, existing_type=sa.DateTime(), nullable=False)
    else:
        op.alter_column(table, column, existing_type=sa.DateTime(), nullable=False)


def _create_foreign_key_if_missing(
    bind,
    table: str,
    name: str,
    column: str,
    target_table: str,
    ondelete: str,
) -> None:
    inspector = sa.inspect(bind)
    if _has_foreign_key(inspector, table, column, target_table):
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(table) as batch:
            batch.create_foreign_key(name, target_table, [column], ["id"], ondelete=ondelete)
    else:
        op.create_foreign_key(name, table, target_table, [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table, column in (
        ("bandit_arm_stats", "updated_at"),
        ("bandit_policies", "created_at"),
        ("experiment_exposures", "exposed_at"),
        ("experiment_metric_aggregates", "updated_at"),
        ("model_training_runs", "started_at"),
        ("model_versions", "created_at"),
    ):
        _make_timestamp_required(bind, table, column)

    inspector = sa.inspect(bind)
    for table, name, column in (
        ("bandit_decisions", "ix_bandit_decisions_policy_id", "policy_id"),
        ("bandit_decisions", "ix_bandit_decisions_context_hash", "context_hash"),
        ("rule_suggestions", "ix_rule_suggestions_converted_workflow_id", "converted_workflow_id"),
    ):
        if table in inspector.get_table_names() and not _has_index(inspector, table, name):
            op.create_index(name, table, [column])
            inspector = sa.inspect(bind)

    _create_foreign_key_if_missing(
        bind,
        "bandit_decisions",
        "fk_bandit_decisions_policy_id_bandit_policies",
        "policy_id",
        "bandit_policies",
        "SET NULL",
    )
    _create_foreign_key_if_missing(
        bind,
        "rule_suggestions",
        "fk_rule_suggestions_converted_workflow_id_workflows",
        "converted_workflow_id",
        "workflows",
        "SET NULL",
    )

    inspector = sa.inspect(bind)
    if (
        bind.dialect.name == "postgresql"
        and settings.EMBEDDING_DIMENSION <= 2000
        and "document_chunks" in inspector.get_table_names()
        and not _has_index(inspector, "document_chunks", "idx_document_chunks_embedding_hnsw")
    ):
        op.execute(
            sa.text(
                "CREATE INDEX idx_document_chunks_embedding_hnsw "
                "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
            )
        )


def downgrade() -> None:
    # This is a forward-only schema safety migration.  Dropping constraints or
    # rewriting timestamps during a rollback could invalidate production data.
    raise RuntimeError("Restore a database backup instead of downgrading schema consistency migration.")
