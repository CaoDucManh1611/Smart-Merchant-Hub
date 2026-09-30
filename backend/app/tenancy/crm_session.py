"""Authenticated CRM session dependency bound to one shop schema."""

from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.tenant_session import tenant_session
from app.db.dependencies import get_db
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.tenancy.schema import schema_name_for


def get_tenant_db(
    tenant: TenantContext = Depends(get_tenant_context),
    legacy_db: Session = Depends(get_db),
) -> Iterator[Session]:
    """Yield a database session whose transaction is routed to this shop only."""

    # The legacy test suite creates an isolated SQLite engine per test class
    # and overrides ``get_db`` to point at it. Reusing that session in test
    # mode keeps converted tenant routes on the same fixture without changing
    # the production two-database contract. Explicit ``get_tenant_db``
    # overrides (used by isolation tests) still take precedence.
    if (
        settings.ENVIRONMENT.strip().lower() == "test"
        and legacy_db.bind is not None
        and legacy_db.bind.dialect.name == "sqlite"
    ):
        legacy_db.info["business_id"] = tenant.business_id
        yield legacy_db
        return

    with tenant_session(schema_name_for(tenant.business_id)) as db:
        db.info["business_id"] = tenant.business_id
        yield db
