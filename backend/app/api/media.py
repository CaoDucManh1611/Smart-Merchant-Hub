from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.dependencies import get_db
from app.services.media_resolver import resolve_media_response, verify_media_url
from app.tenancy.context import TenantContext
from app.tenancy.context import resolve_tenant_context

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
    return resolve_media_response(db, attachment_id=attachment_id, tenant=tenant)
