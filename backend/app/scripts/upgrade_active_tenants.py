"""Upgrade every active shop schema and synchronize the platform registry.

The command is read-only unless ``--apply`` is supplied. It is intended for
additive release migrations after the platform database has already been
upgraded.
"""

from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.database.platform_session import PlatformSessionLocal
from app.database.tenant_session import tenant_engine
from app.models.platform_control import TenantRegistry
from app.tenancy.migration_runner import current_tenant_revision, upgrade_tenant_schema


def upgrade_active_tenants(*, apply: bool) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    with PlatformSessionLocal() as platform_db:
        registries = platform_db.scalars(
            select(TenantRegistry)
            .where(TenantRegistry.state == "active")
            .order_by(TenantRegistry.business_id.asc())
        ).all()

        for registry in registries:
            with tenant_engine.connect() as connection:
                before = current_tenant_revision(connection, registry.schema_name)
                after = before
                if apply:
                    after = upgrade_tenant_schema(connection, registry.schema_name)

            if apply:
                registry.tenant_revision = str(after)
                registry.migration_error = None
                platform_db.commit()

            results.append(
                {
                    "business_id": int(registry.business_id),
                    "schema_name": str(registry.schema_name),
                    "before": before,
                    "after": after,
                    "applied": apply,
                }
            )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Upgrade active tenant schemas")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply migrations and update tenant_registry; omission is a dry run",
    )
    args = parser.parse_args()
    print(json.dumps(upgrade_active_tenants(apply=args.apply), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
