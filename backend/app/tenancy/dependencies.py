"""FastAPI dependencies for trusted tenant contexts and schema sessions."""

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.auth.dependencies import get_current_user, get_optional_user
from app.database.platform_session import get_platform_db
from app.database.tenant_session import tenant_session
from app.db.dependencies import get_db
from app.models.business import User
from app.models.platform_control import TenantRegistry
from app.tenancy.context import TenantContext, resolve_tenant_context


@dataclass(frozen=True)
class AuthenticatedTenant:
    """Tenant identity resolved from the bearer session and platform registry."""

    business_id: int
    schema_name: str
    user_id: int
    role: str


def get_authenticated_tenant(
    user: User = Depends(get_current_user),
    platform_db: Session = Depends(get_platform_db),
) -> AuthenticatedTenant:
    """Resolve a serviceable tenant without accepting a request tenant id."""

    if user.business_id is None:
        raise HTTPException(status_code=403, detail="Tài khoản chưa được gán vào shop.")
    registry = platform_db.scalar(
        select(TenantRegistry).where(
            TenantRegistry.business_id == user.business_id,
            TenantRegistry.state == "active",
            TenantRegistry.feature_enabled.is_(True),
        )
    )
    if registry is None:
        raise HTTPException(
            status_code=423,
            detail={"code": "tenant_unprovisioned", "message": "Shop chưa sẵn sàng."},
        )
    return AuthenticatedTenant(
        business_id=int(user.business_id),
        schema_name=registry.schema_name,
        user_id=int(user.id),
        role=str(user.role or "").strip().lower(),
    )


def get_tenant_db(context: AuthenticatedTenant = Depends(get_authenticated_tenant)):
    """Yield a transaction-local tenant session for the authenticated shop."""

    with tenant_session(context.schema_name) as db:
        yield db


def _enforce_registry_if_available(db: Session, business_id: int) -> None:
    """Fail closed once the platform registry has been migrated.

    Legacy test/demo databases do not have a registry table and continue to
    use the compatibility header path.  A deployed two-database runtime does
    have that table, so an authenticated request must reference an active,
    enabled schema before it can touch tenant APIs.
    """

    try:
        from app.database.platform_session import platform_engine

        if "tenant_registry" not in set(inspect(platform_engine).get_table_names()):
            return
        with platform_engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT state, feature_enabled FROM tenant_registry "
                    "WHERE business_id = :business_id"
                ),
                {"business_id": int(business_id)},
            ).mappings().first()
        if row is None or row["state"] != "active" or not bool(row["feature_enabled"]):
            raise HTTPException(
                status_code=423,
                detail={"code": "tenant_unprovisioned", "message": "Shop chưa sẵn sàng."},
            )
    except HTTPException:
        raise
    except Exception:
        # Registry availability is a readiness concern, not a reason to leak
        # database internals; production callers receive a controlled 503.
        if settings.ENVIRONMENT.strip().lower() == "production":
            raise HTTPException(status_code=503, detail="Tenant registry chưa sẵn sàng.") from None


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


def get_tenant_context(
    request: Request,
    x_business_id: str | None = Header(default=None, alias="X-Business-Id"),
    authenticated_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
    platform_db: Session = Depends(get_platform_db),
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
            development_header=(
                x_business_id if settings.ALLOW_LEGACY_TENANT_HEADER else None
            ),
            environment=settings.ENVIRONMENT,
        )
        _set_database_tenant(db, tenant.business_id)
        if authenticated_user is not None:
            _enforce_registry_if_available(db, tenant.business_id)
        return tenant
    except PermissionError as exc:
        # Tenant resolution is an HTTP boundary.  A bad/missing context must
        # be a controlled client error, never a 500 with internal details.
        raise HTTPException(status_code=403, detail=str(exc)) from exc
