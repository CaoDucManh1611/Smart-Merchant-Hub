"""CLI for a dry-run/resumable migration of one shop."""

from __future__ import annotations

import argparse
import json

from app.database.platform_session import PlatformSessionLocal
from app.database.session import SessionLocal
from app.database.tenant_session import tenant_session
from app.services.tenant_cutover_service import (
    DEFAULT_TABLE_ORDER,
    begin_cutover,
    complete_cutover,
    mark_cutover_verified,
    migrate_business,
    record_migration_results,
    rollback_cutover,
    validate_destination_foreign_keys,
    verify_business,
)
from app.models.platform_control import TenantRegistry
from sqlalchemy import select
from app.tenancy.schema import schema_name_for


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate one shop into its schema")
    parser.add_argument("business_id", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--cutover",
        action="store_true",
        help="Approve the write/cutover phase after reviewing a dry-run report",
    )
    parser.add_argument("--tables", nargs="*", default=list(DEFAULT_TABLE_ORDER))
    parser.add_argument("--complete", metavar="REVISION")
    parser.add_argument("--operation-id", help="Stable audit id for cutover, retry, or rollback")
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Disable the new route and retain the copied schema for a retry",
    )
    args = parser.parse_args()
    business_id = int(args.business_id)

    if not args.dry_run and not args.rollback and not args.cutover and not args.complete:
        parser.error("a write migration requires explicit --cutover approval")
    if args.dry_run and (args.cutover or args.rollback or args.complete):
        parser.error("--dry-run cannot be combined with --cutover, --rollback, or --complete")
    if args.rollback and (args.cutover or args.complete):
        parser.error("--rollback cannot be combined with --cutover or --complete")
    if (args.cutover or args.rollback or args.complete) and not args.operation_id:
        parser.error("--operation-id is required for cutover, complete, and rollback")

    platform_db = PlatformSessionLocal()
    source_db = SessionLocal()
    try:
        registry = platform_db.scalar(
            select(TenantRegistry).where(TenantRegistry.business_id == business_id)
        )
        if registry is None:
            raise RuntimeError("Tenant registry entry not found")
        if str(registry.schema_name) != schema_name_for(business_id):
            raise RuntimeError("Tenant registry schema does not match business")
        if args.rollback:
            rolled_back = rollback_cutover(
                platform_db,
                business_id,
                operation_id=args.operation_id,
                error_code="manual_rollback",
            )
            platform_db.commit()
            print(json.dumps({
                "business_id": int(rolled_back.business_id),
                "schema_name": str(rolled_back.schema_name),
                "state": str(rolled_back.state),
                "feature_enabled": bool(rolled_back.feature_enabled),
                "schema_retained": True,
            }, ensure_ascii=False))
            return 0
        if args.complete and not args.cutover:
            # Completion is intentionally a separate, read-only decision point
            # after the copy/verification command. This gives the operator a
            # chance to review counts and checksums before enabling traffic.
            completed = complete_cutover(
                platform_db,
                business_id,
                operation_id=args.operation_id,
                revision=args.complete,
            )
            platform_db.commit()
            print(json.dumps({
                "business_id": int(completed.business_id),
                "schema_name": str(completed.schema_name),
                "state": str(completed.state),
                "feature_enabled": bool(completed.feature_enabled),
                "tenant_revision": str(completed.tenant_revision or ""),
            }, ensure_ascii=False))
            return 0
        if not args.dry_run:
            begin_cutover(
                platform_db,
                business_id,
                operation_id=args.operation_id,
                approved=True,
            )
            platform_db.commit()
        migration_cursors: dict[str, int | None] = {}
        if not args.dry_run:
            operation = platform_db.scalar(
                select(TenantMigrationOperation).where(
                    TenantMigrationOperation.operation_id == args.operation_id
                )
            )
            if operation is None:
                raise RuntimeError("Tenant migration operation not found after approval")
            # A retry resumes strictly after the last committed cursor for
            # each table. The ledger contains metadata only, never row content.
            migration_cursors = {
                str(table): int(cursor)
                for table, cursor in (operation.cursors or {}).items()
                if cursor is not None
            }
        with tenant_session(schema_name_for(business_id)) as tenant_db:
            results = migrate_business(
                source_db,
                tenant_db,
                business_id=business_id,
                tables=args.tables,
                cursors=migration_cursors,
                dry_run=args.dry_run,
            )
            if not args.dry_run:
                tenant_db.commit()
                report = verify_business(
                    source_db,
                    tenant_db,
                    business_id=business_id,
                    tables=args.tables,
                )
                if not report.ok:
                    raise RuntimeError("Migration verification failed; cutover remains disabled")
                if not validate_destination_foreign_keys(tenant_db):
                    raise RuntimeError("Migration foreign-key verification failed; cutover remains disabled")
        if not args.dry_run:
            record_migration_results(platform_db, args.operation_id, results)
            mark_cutover_verified(platform_db, args.operation_id)
            platform_db.commit()
        if not args.dry_run and args.complete:
            complete_cutover(
                platform_db,
                business_id,
                operation_id=args.operation_id,
                revision=args.complete,
            )
            platform_db.commit()
        print(json.dumps([result.__dict__ for result in results], ensure_ascii=False, default=str))
        return 0
    except Exception:
        platform_db.rollback()
        if not args.dry_run:
            try:
                rollback_cutover(
                    platform_db,
                    business_id,
                    operation_id=args.operation_id,
                )
                platform_db.commit()
            except Exception:
                platform_db.rollback()
        raise
    finally:
        source_db.close()
        platform_db.close()


if __name__ == "__main__":
    raise SystemExit(main())
