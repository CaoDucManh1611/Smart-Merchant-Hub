"""FastAPI dependency for obtaining a trusted tenant context."""

from fastapi import Depends, Header, Request

from app.core.config import settings
from app.tenancy.context import TenantContext, resolve_tenant_context
from app.auth.dependencies import get_optional_user
from app.models.business import User


def get_tenant_context(
    request: Request,
    x_business_id: str | None = Header(default=None, alias="X-Business-Id"),
    authenticated_user: User | None = Depends(get_optional_user),
) -> TenantContext:
    """Resolve tenant set by authentication/webhook middleware or dev header."""
    return resolve_tenant_context(
        authenticated_business_id=(
            authenticated_user.business_id
            if authenticated_user is not None
            else getattr(request.state, "business_id", None)
        ),
        channel_business_id=getattr(request.state, "channel_business_id", None),
        development_header=x_business_id,
        environment=settings.ENVIRONMENT,
    )
