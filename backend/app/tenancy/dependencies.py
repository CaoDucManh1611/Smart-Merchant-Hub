"""FastAPI dependency for obtaining a trusted tenant context."""

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.tenancy.context import TenantContext, resolve_tenant_context
from app.auth.dependencies import get_optional_user
from app.models.business import User
from app.db.dependencies import get_db


def _set_database_tenant(db: Session, business_id: int) -> None:
    """Set the transaction-local tenant used by PostgreSQL RLS policies.

    SQLite and other development databases do not expose ``set_config``;
    explicit ``business_id`` predicates remain the primary compatibility
    boundary there.
    """
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    db.execute(
        text("SELECT set_config('app.business_id', :business_id, true)"),
        {"business_id": str(int(business_id))},
    )


def set_platform_database_context(db: Session) -> None:
    """Allow an authenticated platform admin to inspect all tenants.

    The flag is transaction-local and is only set after the platform
    membership dependency has passed.
    """
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    db.execute(text("SELECT set_config('app.platform_admin', 'true', true)"))


def get_tenant_context(
    request: Request,
    x_business_id: str | None = Header(default=None, alias="X-Business-Id"),
    authenticated_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
) -> TenantContext:
    """Resolve tenant set by authentication/webhook middleware or dev header."""
    try:
        tenant = resolve_tenant_context(
            authenticated_business_id=(
                authenticated_user.business_id
                if authenticated_user is not None
                else getattr(request.state, "business_id", None)
            ),
            channel_business_id=getattr(request.state, "channel_business_id", None),
            development_header=x_business_id,
            environment=settings.ENVIRONMENT,
        )
        _set_database_tenant(db, tenant.business_id)
        return tenant
    except PermissionError as exc:
        # Tenant resolution is an HTTP boundary.  A bad/missing context must
        # be a controlled client error, never a 500 with internal details.
        raise HTTPException(status_code=403, detail=str(exc)) from exc
