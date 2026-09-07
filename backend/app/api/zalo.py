"""Zalo Bot Creator webhook endpoint."""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.integrations import get_channel_adapter
from app.services.channel_event_service import ingest_normalized_events
from app.services.channel_credentials import decrypt_token
from app.services.message_service import process_and_save_message
from app.services.realtime import manager
from app.core.config import settings
from app.tenancy.webhook import (
    resolve_zalo_channel,
    resolve_zalo_oa_channel,
    verify_zalo_oa_signature,
)


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("")
async def receive_zalo_webhook(
    request: Request,
    payload: dict,
    db: Session = Depends(get_db),
    x_bot_api_secret_token: str | None = Header(default=None),
    x_zevent_signature: str | None = Header(default=None),
):
    """Receive Zalo Bot Creator or Official Account events."""
    raw_body = await request.body()
    # Zalo's developer console sends an empty POST as a connectivity probe
    # before it starts delivering signed events.  It carries no user data, so
    # acknowledging only this exact empty payload is safe and keeps the
    # webhook setup flow from being rejected as an unauthenticated message.
    if not payload:
        return {"status": "received", "processed": 0}
    if x_zevent_signature:
        channel = resolve_zalo_oa_channel(db, payload)
        if channel is None:
            raise HTTPException(status_code=401, detail="Invalid Zalo OA webhook channel")
        config = channel.config if isinstance(channel.config, dict) else {}
        oa_secret_key = config.get("oa_secret_key")
        if not oa_secret_key and config.get("oa_secret_key_encrypted"):
            try:
                oa_secret_key = decrypt_token(
                    config["oa_secret_key_encrypted"],
                    settings.CHANNEL_ENCRYPTION_KEY,
                )
            except (ValueError, TypeError):
                logger.warning("Unable to decrypt Zalo OA webhook secret", exc_info=True)
        app_id = config.get("oa_app_id") or config.get("app_id") or payload.get("app_id")
        if not verify_zalo_oa_signature(
            raw_body,
            signature=x_zevent_signature,
            app_id=str(app_id or ""),
            timestamp=str(payload.get("timestamp") or ""),
            oa_secret_key=str(oa_secret_key or ""),
        ):
            raise HTTPException(status_code=401, detail="Invalid Zalo OA webhook signature")
    else:
        channel = resolve_zalo_channel(db, x_bot_api_secret_token)
        if channel is None:
            raise HTTPException(status_code=401, detail="Invalid Zalo webhook secret")

    adapter = get_channel_adapter("zalo")
    access_token = None
    if channel.access_token_encrypted:
        try:
            access_token = decrypt_token(
                channel.access_token_encrypted,
                settings.CHANNEL_ENCRYPTION_KEY,
            )
        except (ValueError, TypeError):
            logger.warning("Unable to decrypt Zalo profile token", exc_info=True)
    events = adapter.parse_events(
        payload,
        external_account_id=channel.external_account_id,
    )
    accepted_events = ingest_normalized_events(db, events)
    processed = 0
    for event in accepted_events:
        for item in event.messages:
            profile = item.metadata or {}
            if not profile.get("avatar_url") and access_token:
                try:
                    profile = {
                        **profile,
                        **adapter.fetch_user_profile(
                            user_id=item.sender_external_id,
                            access_token=access_token,
                        ),
                    }
                except Exception:
                    logger.info(
                        "Zalo profile enrichment unavailable for user %s",
                        item.sender_external_id,
                        exc_info=True,
                    )
            saved = process_and_save_message(
                db=db,
                message={
                    "channel": event.provider.value,
                    "external_account_id": event.external_account_id,
                    "external_user_id": item.sender_external_id,
                    "external_message_id": item.external_message_id,
                    "content": item.text,
                    "name": profile.get("display_name"),
                    "display_name": profile.get("display_name"),
                    "avatar_url": profile.get("avatar_url"),
                    "media_type": item.message_type.value,
                    "media_url": item.attachments[0].url if item.attachments else None,
                    "attachments": [attachment.model_dump(mode="json") for attachment in item.attachments],
                    "raw_payload": event.raw_payload,
                    "business_id": event.business_id,
                    "channel_id": event.channel_id,
                },
            )
            if isinstance(saved, dict):
                processed += 1
                await manager.broadcast(
                    {
                        "type": "message_created",
                        "conversation_id": saved.get("conversation_id"),
                        "message": saved,
                    }
                )

    return {"status": "received", "processed": processed}
