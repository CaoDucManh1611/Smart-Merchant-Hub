"""Operational cutover helpers for one shop at a time."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Iterable, Mapping

from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.orm import Session

from app.models.platform_control import TenantMigrationOperation, TenantRegistry
from app.services.tenant_data_migration import (
    TableMigrationResult,
    checksum_rows,
    migrate_table,
    verify_table_counts,
)
from app.tenancy.schema import schema_name_for, validate_schema_name


DEFAULT_TABLE_ORDER = (
    "customers",
    "customer_identities",
    "customer_contacts",
    "customer_addresses",
    "customer_facts",
    "customer_notes",
    "customer_merges",
    "customer_merge_operations",
    "customer_segments",
    "customer_tags",
    "customer_collection_sessions",
    "customer_verification_challenges",
    "customer_consents",
    "channels",
    "channel_events",
    "conversations",
    "conversation_assignments",
    "conversation_tags",
    "tags",
    "messages",
    "message_attachments",
    "products",
    "orders",
    "order_items",
    "order_events",
    "order_payments",
    "suppliers",
    "purchase_orders",
    "purchase_order_items",
    "purchase_receipts",
    "purchase_receipt_items",
    "stock_movements",
    "documents",
    "document_chunks",
    "app_settings",
    "business_settings",
    "workflows",
    "workflow_runs",
    "tickets",
    "ticket_comments",
    "ticket_events",
    "notifications",
    "leads",
    "lead_activities",
    "lead_conversions",
    "revenue_touchpoints",
    "revenue_attributions",
    "permission_overrides",
    "customer_feedback",
    "rule_suggestions",
    "feature_snapshots",
    "experiments",
    "experiment_assignments",
    "experiment_exposures",
    "experiment_outcomes",
    "experiment_metric_aggregates",
    "model_versions",
    "model_training_runs",
    "model_evaluation_metrics",
    "bandit_policies",
    "bandit_arm_stats",
    "bandit_decisions",
    "recommendation_requests",
    "recommendation_feedback",
    "recommendation_customer_profiles",
    "recommendation_training_runs",
    "customer_product_interactions",
    "chatbot_configs",
    "chatbot_followups",
    "canned_responses",
    "crm_jobs",
    "rag_runs",
    "oauth_states",
    "channel_migration_audits",
    "audit_logs",
    "data_lifecycle_requests",
)


_PARENT_BUSINESS_KEYS: dict[str, tuple[str, str]] = {
    # Child rows do not repeat business_id in the legacy schema.  Always
    # constrain them through their tenant-owned parent instead of copying all
    # shops' rows into the destination schema.
    "messages": ("conversations", "conversation_id"),
    "message_attachments": ("messages", "message_id"),
    "channel_events": ("channels", "channel_id"),
    "conversation_assignments": ("conversations", "conversation_id"),
    "document_chunks": ("documents", "document_id"),
    "order_items": ("orders", "order_id"),
    "purchase_order_items": ("purchase_orders", "purchase_order_id"),
    "purchase_receipt_items": ("purchase_receipts", "receipt_id"),
    "conversation_tags": ("conversations", "conversation_id"),
    "customer_merge_operations": ("customer_merges", "customer_merge_id"),
}


def _source_tables_for_ownership(names: Iterable[str]) -> set[str]:
    """Return requested tables plus every parent needed for ownership joins."""
    required = {str(name).strip() for name in names if str(name).strip()}
    pending = list(required)
    while pending:
        child = pending.pop()
        relation = _PARENT_BUSINESS_KEYS.get(child)
        if relation is None or relation[0] in required:
            continue
        required.add(relation[0])
        pending.append(relation[0])
    return required


def _rows(
    connection,
    table: Table,
    business_id: int,
    *,
    metadata: MetaData | None = None,
) -> list[dict]:
    query = select(table)
    if "business_id" in table.c:
        query = query.where(table.c.business_id == int(business_id))
    else:
        if metadata is None:
            return []
        # Walk the ownership chain (for example
        # message_attachments -> messages -> conversations) until a parent
        # carries business_id.  Joining only the immediate parent would
        # silently drop nested child rows from a migration.
        current = table
        visited: set[str] = set()
        while "business_id" not in current.c:
            if current.name in visited:
                return []
            visited.add(current.name)
            relation = _PARENT_BUSINESS_KEYS.get(current.name)
            parent = metadata.tables.get(relation[0]) if relation else None
            if parent is None or relation[1] not in current.c:
                # A table without a complete ownership chain is not safe to
                # migrate automatically. Skipping is safer than importing
                # another shop's rows.
                return []
            query = query.join(parent, current.c[relation[1]] == parent.c.id)
            current = parent
        query = query.where(current.c.business_id == int(business_id))
    return [dict(row) for row in connection.execute(query).mappings().all()]


def _reflect_existing(metadata: MetaData, bind, names: list[str]) -> None:
    """Reflect only tables present in a legacy database.

    Pilot migrations run against databases at different schema revisions. A
    missing optional table must be skipped instead of making the whole shop
    migration fail while SQLAlchemy inspects a non-existent relation.
    """

    from sqlalchemy import inspect

    available = set(inspect(bind).get_table_names())
    selected = [name for name in names if name in available]
    if selected:
        metadata.reflect(bind=bind, only=selected)


def migrate_business(
    source_db: Session,
    tenant_db: Session,
    *,
    business_id: int,
    tables: Iterable[str] = DEFAULT_TABLE_ORDER,
    cursors: Mapping[str, int | None] | None = None,
    dry_run: bool = False,
) -> list[TableMigrationResult]:
    """Copy legacy rows for exactly one business into the current schema.

    The destination session must already be routed to ``shop_<business_id>``.
    Source rows are read-only; callers commit the destination only after all
    checks pass.  Re-running with returned cursors resumes without duplicates.
    """
    if int(business_id) <= 0:
        raise ValueError("business_id must be positive")
    metadata = MetaData()
    names = [str(name).strip() for name in tables if str(name).strip()]
    source_reflect_names = _source_tables_for_ownership(names)
    _reflect_existing(metadata, source_db.bind, sorted(source_reflect_names))
    destination = MetaData()
    # Reflect through the tenant session's connection, not the raw engine.
    # ``tenant_session`` installs ``search_path`` transaction-locally in its
    # ``after_begin`` hook; reflecting from ``tenant_db.bind`` would silently
    # inspect ``public`` and skip every shop table.
    _reflect_existing(destination, tenant_db.connection(), names)
    results: list[TableMigrationResult] = []
    for name in names:
        source_table = metadata.tables.get(name)
        destination_table = destination.tables.get(name)
        if source_table is None or destination_table is None:
            continue
        source_rows = _rows(source_db, source_table, business_id, metadata=metadata)
        cursor = (cursors or {}).get(name)
        accepted = [row for row in source_rows if cursor is None or int(row.get("id", 0)) > int(cursor)]

        def write_row(row: Mapping[str, object], target=destination_table) -> None:
            values = {column.name: row[column.name] for column in target.columns if column.name in row}
            tenant_db.execute(target.insert().values(**values))

        result = migrate_table(
            table=name,
            source_rows=source_rows,
            write_row=write_row,
            cursor=cursor,
            dry_run=dry_run,
        )
        results.append(result)
    return results


@dataclass(frozen=True)
class TableVerification:
    """Count/checksum result for one migrated tenant table."""

    table: str
    source_rows: int
    destination_rows: int
    source_checksum: str
    destination_checksum: str
    matches: bool


@dataclass(frozen=True)
class VerificationReport:
    """Read-only verification result for one shop migration."""

    business_id: int
    tables: tuple[TableVerification, ...]

    @property
    def ok(self) -> bool:
        return all(item.matches for item in self.tables)


def verify_business(
    source_db: Session,
    tenant_db: Session,
    *,
    business_id: int,
    tables: Iterable[str] = DEFAULT_TABLE_ORDER,
) -> VerificationReport:
    """Compare legacy and schema-local rows without mutating either side.

    The destination is reflected through the already routed tenant session so
    two shops can have identical primary keys without cross-schema reads.
    Only row counts and SHA-256 checksums are returned to callers/CLI output.
    """
    if int(business_id) <= 0:
        raise ValueError("business_id must be positive")
    names = [str(name).strip() for name in tables if str(name).strip()]
    source_metadata = MetaData()
    source_reflect_names = _source_tables_for_ownership(names)
    _reflect_existing(source_metadata, source_db.bind, sorted(source_reflect_names))
    destination_metadata = MetaData()
    _reflect_existing(destination_metadata, tenant_db.connection(), names)
    checks: list[TableVerification] = []
    for name in names:
        source_table = source_metadata.tables.get(name)
        destination_table = destination_metadata.tables.get(name)
        if source_table is None or destination_table is None:
            # Missing objects are mismatches, but do not expose table content.
            checks.append(TableVerification(name, 0, 0, "", "", False))
            continue
        source_rows = _rows(source_db, source_table, business_id, metadata=source_metadata)
        destination_query = select(destination_table)
        if "business_id" in destination_table.c:
            destination_query = destination_query.where(
                destination_table.c.business_id == int(business_id)
            )
        destination_rows = [
            dict(row)
            for row in tenant_db.execute(destination_query).mappings().all()
        ]
        source_checksum = checksum_rows(source_rows)
        destination_checksum = checksum_rows(destination_rows)
        checks.append(
            TableVerification(
                table=name,
                source_rows=len(source_rows),
                destination_rows=len(destination_rows),
                source_checksum=source_checksum,
                destination_checksum=destination_checksum,
                matches=verify_table_counts(source_rows, destination_rows),
            )
        )
    return VerificationReport(int(business_id), tuple(checks))


def validate_destination_foreign_keys(tenant_db: Session) -> bool:
    """Validate schema-local foreign keys without returning row content."""

    dialect = tenant_db.get_bind().dialect.name
    if dialect == "sqlite":
        return tenant_db.execute(text("PRAGMA foreign_key_check")).first() is None
    if dialect == "postgresql":
        tenant_db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        invalid = tenant_db.execute(
            text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE contype='f' AND connamespace = current_schema()::regnamespace "
                "AND convalidated IS NOT TRUE"
            )
        ).scalar_one()
        return int(invalid or 0) == 0
    return True


def _migration_operation(platform_db: Session, operation_id: str) -> TenantMigrationOperation:
    operation = platform_db.scalar(
        select(TenantMigrationOperation).where(
            TenantMigrationOperation.operation_id == str(operation_id)
        ).with_for_update()
    )
    if operation is None:
        raise LookupError("Tenant migration operation not found")
    return operation


def begin_cutover(
    platform_db: Session,
    business_id: int,
    *,
    operation_id: str,
    approved: bool,
) -> TenantRegistry:
    """Move a registry entry to ``migrating`` without deleting any schema."""
    if not approved:
        raise PermissionError("Cutover requires explicit operator approval")
    normalized_operation_id = str(operation_id).strip()
    if not normalized_operation_id or len(normalized_operation_id) > 64:
        raise ValueError("operation_id must contain 1-64 characters")
    registry = platform_db.scalar(select(TenantRegistry).where(TenantRegistry.business_id == int(business_id)).with_for_update())
    if registry is None:
        raise LookupError("Tenant registry entry not found")
    if validate_schema_name(registry.schema_name) != schema_name_for(business_id):
        raise ValueError("Tenant registry schema does not match business")
    if registry.state not in {"ready", "active", "error"}:
        raise RuntimeError(f"Cannot start cutover from state {registry.state}")
    registry.state = "migrating"
    registry.feature_enabled = False
    registry.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    existing = platform_db.scalar(
        select(TenantMigrationOperation).where(
            TenantMigrationOperation.operation_id == normalized_operation_id
        )
    )
    if existing is not None:
        if existing.business_id != int(business_id):
            raise ValueError("operation_id already belongs to another business")
        if existing.state not in {"failed", "rolled_back"}:
            raise RuntimeError("migration operation is already active")
        existing.state = "migrating"
        existing.error_code = None
        existing.approved_at = datetime.now(timezone.utc).replace(tzinfo=None)
        existing.verified_at = None
        existing.completed_at = None
    else:
        platform_db.add(
            TenantMigrationOperation(
                operation_id=normalized_operation_id,
                business_id=int(business_id),
                state="migrating",
                cursors={},
                row_counts={},
                checksums={},
                approved_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )
    platform_db.flush()
    return registry


def record_migration_results(
    platform_db: Session,
    operation_id: str,
    results: Iterable[TableMigrationResult],
) -> TenantMigrationOperation:
    operation = _migration_operation(platform_db, operation_id)
    if operation.state != "migrating":
        raise RuntimeError("migration operation is not accepting copy results")
    result_list = list(results)
    operation.cursors = {
        **dict(operation.cursors or {}),
        **{item.table: item.cursor for item in result_list if item.cursor is not None},
    }
    operation.row_counts = {
        **dict(operation.row_counts or {}),
        **{
            item.table: {"source": int(item.source_rows), "copied": int(item.copied_rows)}
            for item in result_list
        },
    }
    operation.checksums = {
        **dict(operation.checksums or {}),
        **{
            item.table: {
                "source": str(item.source_checksum),
                "destination": str(item.destination_checksum),
            }
            for item in result_list
        },
    }
    operation.state = "copied"
    platform_db.flush()
    return operation


def mark_cutover_verified(platform_db: Session, operation_id: str) -> TenantMigrationOperation:
    operation = _migration_operation(platform_db, operation_id)
    if operation.state != "copied":
        raise RuntimeError("migration operation must be copied before verification")
    operation.state = "verified"
    operation.verified_at = datetime.now(timezone.utc).replace(tzinfo=None)
    platform_db.flush()
    return operation


def complete_cutover(
    platform_db: Session,
    business_id: int,
    *,
    operation_id: str,
    revision: str,
) -> TenantRegistry:
    operation = _migration_operation(platform_db, operation_id)
    if operation.business_id != int(business_id) or operation.state != "verified":
        raise RuntimeError("Tenant migration operation is not verified")
    registry = platform_db.scalar(select(TenantRegistry).where(TenantRegistry.business_id == int(business_id)).with_for_update())
    if registry is None or registry.state != "migrating":
        raise RuntimeError("Tenant is not in migrating state")
    registry.tenant_revision = str(revision).strip() or None
    registry.state = "active"
    registry.feature_enabled = True
    registry.migration_error = None
    registry.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    operation.state = "active"
    operation.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    platform_db.flush()
    return registry


def rollback_cutover(
    platform_db: Session,
    business_id: int,
    *,
    operation_id: str | None = None,
    error_code: str = "cutover_rolled_back",
) -> TenantRegistry:
    """Disable routing while retaining all tenant data for a retry."""
    registry = platform_db.scalar(select(TenantRegistry).where(TenantRegistry.business_id == int(business_id)).with_for_update())
    if registry is None:
        raise LookupError("Tenant registry entry not found")
    registry.state = "error"
    registry.feature_enabled = False
    registry.migration_error = str(error_code).strip()[:80] or "cutover_failed"
    registry.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    if operation_id:
        operation = _migration_operation(platform_db, operation_id)
        if operation.business_id != int(business_id):
            raise ValueError("migration operation belongs to another business")
        operation.state = "rolled_back"
        operation.error_code = registry.migration_error
        operation.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    platform_db.flush()
    return registry


__all__ = [
    "DEFAULT_TABLE_ORDER",
    "begin_cutover",
    "complete_cutover",
    "mark_cutover_verified",
    "migrate_business",
    "record_migration_results",
    "TableVerification",
    "VerificationReport",
    "verify_business",
    "validate_destination_foreign_keys",
    "rollback_cutover",
]
