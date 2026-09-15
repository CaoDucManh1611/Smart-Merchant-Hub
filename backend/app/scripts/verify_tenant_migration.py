"""Read-only verifier for one shop's legacy-to-schema migration.

The command prints counts and checksums only.  It never selects a schema from
request data and never deletes or overwrites tenant rows.
"""

from __future__ import annotations

import argparse
import json

from app.database.platform_session import PlatformSessionLocal
from app.database.session import SessionLocal
from app.database.tenant_session import tenant_session
from app.services.tenant_cutover_service import (
    DEFAULT_TABLE_ORDER,
    verify_business,
)
from app.models.platform_control import TenantRegistry
from sqlalchemy import select
from app.tenancy.schema import schema_name_for


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify one shop migration")
    parser.add_argument("business_id", type=int)
    parser.add_argument("--tables", nargs="*", default=list(DEFAULT_TABLE_ORDER))
    args = parser.parse_args()
    business_id = int(args.business_id)

    # Open the platform session to validate that the target shop exists and is
    # registered.  The comparison itself remains source + tenant only.
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
        platform_db.close()


if __name__ == "__main__":
    raise SystemExit(main())
