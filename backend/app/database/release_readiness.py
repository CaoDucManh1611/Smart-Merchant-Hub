"""Read-only production database and migration readiness checks."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from app.database.platform_session import platform_engine
from app.database.tenant_session import tenant_engine


PLATFORM_HEAD = "20260915_0004"
TENANT_HEAD = "20260915_0001"


@dataclass(frozen=True)
class ReleaseDatabaseReadiness:
    platform_revision: str
    tenant_revision: str
    active_tenants: int
    incompatible_tenants: int


def assert_release_database_ready() -> ReleaseDatabaseReadiness:
    """Fail closed without creating, altering, or seeding any database object."""

    with platform_engine.connect() as platform:
        platform_revision = platform.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        if platform_revision != PLATFORM_HEAD:
            raise RuntimeError("platform database migration head is not compatible")
        row = platform.execute(
            text(
                "SELECT count(*) FILTER (WHERE state='active') AS active, "
                "count(*) FILTER (WHERE state='active' AND "
                "(tenant_revision IS DISTINCT FROM :head OR feature_enabled IS NOT TRUE)) AS incompatible "
                "FROM tenant_registry"
            ),
            {"head": TENANT_HEAD},
        ).mappings().one()

    with tenant_engine.connect() as tenant:
        tenant.execute(text("SELECT 1"))
        vector_available = tenant.execute(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')")
        ).scalar_one()
        if not vector_available:
            raise RuntimeError("tenant database requires the vector extension")

    incompatible = int(row["incompatible"] or 0)
    if incompatible:
        raise RuntimeError("one or more active tenant schemas are not at the required migration head")
    return ReleaseDatabaseReadiness(
        platform_revision=str(platform_revision),
        tenant_revision=TENANT_HEAD,
        active_tenants=int(row["active"] or 0),
        incompatible_tenants=incompatible,
    )


__all__ = [
    "PLATFORM_HEAD",
    "TENANT_HEAD",
    "ReleaseDatabaseReadiness",
    "assert_release_database_ready",
]
