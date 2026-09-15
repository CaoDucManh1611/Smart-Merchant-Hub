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
    migrate_business,
    rollback_cutover,
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
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Disable the new route and retain the copied schema for a retry",
    )
    args = parser.parse_args()
    business_id = int(args.business_id)

    if not args.dry_run and not args.rollback and not args.cutover:
        parser.error("a write migration requires explicit --cutover approval")
    if args.dry_run and args.cutover:
        parser.error("--dry-run cannot be combined with --cutover")
    if args.rollback and args.cutover:
        parser.error("--rollback cannot be combined with --cutover")

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
            if args.dry_run or args.complete:
                parser.error("--rollback cannot be combined with --dry-run or --complete")
            rolled_back = rollback_cutover(
                platform_db,
                business_id,
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
        if not args.dry_run:
            begin_cutover(platform_db, business_id)
            platform_db.commit()
        with tenant_session(schema_name_for(business_id)) as tenant_db:
            results = migrate_business(
                source_db,
                tenant_db,
                business_id=business_id,
                tables=args.tables,
                dry_run=args.dry_run,
            )
        if not args.dry_run and args.complete:
            complete_cutover(platform_db, business_id, revision=args.complete)
            platform_db.commit()
        print(json.dumps([result.__dict__ for result in results], ensure_ascii=False, default=str))
        return 0
    except Exception:
        platform_db.rollback()
        if not args.dry_run:
            try:
                rollback_cutover(platform_db, business_id)
                platform_db.commit()
            except Exception:
                platform_db.rollback()
        raise
    finally:
        source_db.close()
        platform_db.close()


if __name__ == "__main__":
    raise SystemExit(main())
