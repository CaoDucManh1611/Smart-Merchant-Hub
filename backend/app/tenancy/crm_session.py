"""Authenticated CRM session dependency bound to one shop schema."""

from collections.abc import Iterator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.database.tenant_session import tenant_session
from app.tenancy.context import TenantContext
from app.tenancy.dependencies import get_tenant_context
from app.tenancy.schema import schema_name_for


def get_tenant_db(
    tenant: TenantContext = Depends(get_tenant_context),
) -> Iterator[Session]:
    """Yield a database session whose transaction is routed to this shop only."""

    with tenant_session(schema_name_for(tenant.business_id)) as db:
        db.info["business_id"] = tenant.business_id
        yield db
