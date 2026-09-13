"""Browser-safe proxy for provider-backed customer avatars."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.dependencies import get_db
from app.integrations.telegram import TelegramAdapter
from app.integrations.zalo import ZaloAdapter
from app.models.channel import Channel
from app.models.customer import Customer
from app.models.customer_identity import CustomerIdentity
from app.services.channel_credentials import decrypt_token
from app.services.customer_avatar import verify_customer_avatar_url
from app.services.message_service import fetch_instagram_customer_profile
from app.tenancy.context import TenantContext, resolve_tenant_context


router = APIRouter()


@router.get("/{customer_id}/avatar")
def get_customer_avatar(
    customer_id: int,
    request: Request,
    business_id: int | None = Query(default=None),
    expires: int | None = Query(default=None),
    signature: str | None = Query(default=None),
    db: Session = Depends(get_db),
    x_business_id: str | None = Header(default=None, alias="X-Business-Id"),
):
    """Stream a provider profile photo without exposing channel credentials."""
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
            or not verify_customer_avatar_url(
                customer_id=customer_id,
                business_id=business_id,
                expires=expires,
                signature=signature,
            )
        ):
            raise HTTPException(status_code=401, detail="Tenant context is required") from None
        tenant = TenantContext(int(business_id), "signed_customer_avatar_url")

    customer = db.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.business_id == tenant.business_id,
        )
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer avatar not found")

    identity = db.scalar(
        select(CustomerIdentity)
        .where(
            CustomerIdentity.business_id == tenant.business_id,
            CustomerIdentity.customer_id == customer.id,
            CustomerIdentity.channel == customer.channel,
        )
        .order_by(CustomerIdentity.last_seen_at.desc())
    )
    if identity is None:
        raise HTTPException(status_code=404, detail="Customer avatar not available")

    channel = db.scalar(
        select(Channel).where(
            Channel.business_id == tenant.business_id,
            Channel.channel_type == customer.channel,
            Channel.external_account_id == identity.external_account_id,
            Channel.status == "active",
        )
    )
    if channel is None:
        # Imported conversations can retain an older account identifier even
        # after the shop reconnects the same provider.  A tenant's current
        # active connection is still the correct credential source.
        active_channels = db.scalars(
            select(Channel).where(
                Channel.business_id == tenant.business_id,
                Channel.channel_type == customer.channel,
                Channel.status == "active",
            )
        ).all()
        channel = active_channels[0] if len(active_channels) == 1 else None
    if channel is None or not channel.access_token_encrypted:
        raise HTTPException(status_code=404, detail="Customer avatar not available")

    try:
        access_token = decrypt_token(
            channel.access_token_encrypted,
            settings.CHANNEL_ENCRYPTION_KEY,
        )
        if customer.channel == "telegram":
            adapter = TelegramAdapter()
            file_path = adapter.fetch_profile_avatar_file_path(
                user_id=identity.external_user_id,
                access_token=access_token,
            )
            if not file_path:
                raise HTTPException(status_code=404, detail="Customer avatar not available")
            provider_url = adapter.build_file_url(
                file_path=file_path,
                access_token=access_token,
            )
        elif customer.channel == "zalo":
            profile = ZaloAdapter().fetch_user_profile(
                user_id=identity.external_user_id,
                access_token=access_token,
            )
            provider_url = str(profile.get("avatar_url") or "").strip()
        elif customer.channel == "instagram":
            profile = fetch_instagram_customer_profile(
                identity.external_user_id,
                access_token=access_token,
            )
            provider_url = str(profile.get("avatar_url") or "").strip()
        else:
            raise HTTPException(status_code=404, detail="Customer avatar not available")
        if not provider_url:
            raise HTTPException(status_code=404, detail="Customer avatar not available")
        response = httpx.get(
            provider_url,
            timeout=20,
            follow_redirects=True,
        )
        response.raise_for_status()
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Unable to download customer avatar") from exc

    media_type = response.headers.get("content-type") or "image/jpeg"
    if not media_type.startswith("image/"):
        media_type = "image/jpeg"
    return StreamingResponse(
        iter([response.content]),
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=300"},
    )
