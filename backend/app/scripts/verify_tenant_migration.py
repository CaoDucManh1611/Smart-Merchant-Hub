"""Read-only verifier for one shop's legacy-to-schema migration.

The command prints counts and checksums only.  It never selects a schema from
request data and never deletes or overwrites tenant rows.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from app.database.platform_session import PlatformSessionLocal
from app.database.tenant_session import tenant_session
from app.scripts.sqlite_snapshot import validate_sqlite_snapshot
from app.services.tenant_cutover_service import (
    DEFAULT_TABLE_ORDER,
    verify_business,
)
from app.models.platform_control import TenantRegistry
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.tenancy.schema import schema_name_for


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify one shop migration")
    parser.add_argument("business_id", type=int)
    parser.add_argument("--sqlite-backup", type=Path, help="Read-only SQLite snapshot used by the migration")
    parser.add_argument("--tables", nargs="*", default=list(DEFAULT_TABLE_ORDER))
    args = parser.parse_args()
    business_id = int(args.business_id)

    # Open the platform session to validate that the target shop exists and is
    # registered.  The comparison itself remains source + tenant only.
    platform_db = PlatformSessionLocal()
    source_engine = None
    if args.sqlite_backup:
        snapshot_info = validate_sqlite_snapshot(args.sqlite_backup)
        snapshot = Path(str(snapshot_info["path"]))
        source_engine = create_engine(
            "sqlite+pysqlite://",
            creator=lambda: sqlite3.connect(f"{snapshot.as_uri()}?mode=ro", uri=True, timeout=30),
        )
        source_db = sessionmaker(bind=source_engine, autoflush=False, autocommit=False)()
    else:
        from app.database.session import SessionLocal
        source_db = SessionLocal()
    try:
        registry = platform_db.scalar(
            select(TenantRegistry).where(TenantRegistry.business_id == business_id)
        )
        if registry is None:
            raise RuntimeError("Tenant registry entry not found")
        if str(registry.schema_name) != schema_name_for(business_id):
            raise RuntimeError("Tenant registry schema does not match business")
        with tenant_session(schema_name_for(business_id)) as tenant_db:
            tenant_db.info["business_id"] = business_id
            report = verify_business(
                source_db,
                tenant_db,
                business_id=business_id,
                tables=args.tables,
            )
        print(
            json.dumps(
                {
                    "business_id": report.business_id,
                    "ok": report.ok,
                    "tables": [item.__dict__ for item in report.tables],
                },
                ensure_ascii=False,
            )
        )
        return 0 if report.ok else 2
    finally:
        source_db.close()
        if source_engine is not None:
            source_engine.dispose()
        platform_db.close()


if __name__ == "__main__":
    raise SystemExit(main())
