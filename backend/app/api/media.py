from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.dependencies import get_db
from app.database.tenant_session import tenant_session
from app.services.media_resolver import resolve_media_response, verify_media_url
from app.tenancy.context import TenantContext
from app.tenancy.context import resolve_tenant_context
from app.tenancy.schema import schema_name_for

router = APIRouter()


@router.get("/{attachment_id}")
def get_media_attachment(
    attachment_id: int,
    request: Request,
    business_id: int | None = Query(default=None),
    expires: int | None = Query(default=None),
    signature: str | None = Query(default=None),
    db: Session = Depends(get_db),
    x_business_id: str | None = Header(default=None, alias="X-Business-Id"),
):
    # Normal API calls continue to use the authenticated/header tenant. Media
    # tags cannot send that header, so a signed URL is accepted as a narrowly
    # scoped alternative and never as an unsigned business-id selector.
    try:
        tenant = resolve_tenant_context(
            authenticated_business_id=getattr(request.state, "business_id", None),
            channel_business_id=getattr(request.state, "channel_business_id", None),
            development_header=x_business_id,
            environment=settings.ENVIRONMENT,
        )
    except PermissionError:
        if (
            business_id is None
            or expires is None
            or not signature
            or not verify_media_url(
                attachment_id=attachment_id,
                business_id=business_id,
                expires=expires,
                signature=signature,
            )
        ):
            raise HTTPException(status_code=401, detail="Tenant context is required") from None
        tenant = TenantContext(int(business_id), "signed_media_url")
    # Browser media tags use the signed URL branch and cannot send the
    # tenant header.  Route that request through the shop schema; the legacy
    # compatibility session points at the control-plane database and cannot
    # see attachments stored in ``shop_<business_id>``.
    if tenant.source == "signed_media_url":
        with tenant_session(schema_name_for(tenant.business_id)) as tenant_db:
            return resolve_media_response(tenant_db, attachment_id=attachment_id, tenant=tenant)
    return resolve_media_response(db, attachment_id=attachment_id, tenant=tenant)
