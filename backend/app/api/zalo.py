"""Zalo Bot Creator/Official Account webhook ingress."""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.platform_session import get_platform_db
from app.database.tenant_session import tenant_session
from app.integrations import get_channel_adapter
from app.models.channel import Channel
from app.services.channel_credentials import decrypt_token
from app.services.channel_event_service import (
    ingest_normalized_events,
    mark_channel_event_failed,
    mark_channel_event_processed,
)
from app.services.message_service import process_and_save_message
from app.services.realtime import manager
from app.tenancy.registry import resolve_webhook_route
from app.tenancy.webhook import verify_zalo_oa_signature


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("")
async def receive_zalo_webhook(
    request: Request,
    payload: dict,
    platform_db: Session = Depends(get_platform_db),
    x_bot_api_secret_token: str | None = Header(default=None),
    x_zevent_signature: str | None = Header(default=None),
):
    """Resolve a platform route before opening the shop schema."""
    if not payload:
        return {"status": "received", "processed": 0}

    if x_zevent_signature:
        recipient = payload.get("recipient")
        recipient_id = recipient.get("id") if isinstance(recipient, dict) else None
        route_key = str(payload.get("oa_id") or recipient_id or payload.get("app_id") or "").strip()
    else:
        route_key = str(x_bot_api_secret_token or "").strip()
    if not route_key:
        raise HTTPException(status_code=401, detail="Invalid Zalo webhook route")
    try:
        route = resolve_webhook_route(platform_db, "zalo", route_key)
    except RuntimeError:
        route = None
    if route is None:
        raise HTTPException(status_code=401, detail="Invalid Zalo webhook route")

    raw_body = await request.body()
    with tenant_session(route.schema_name) as db:
        channel = db.get(Channel, route.channel_id)
        if channel is None or channel.channel_type != "zalo" or channel.status != "active":
            raise HTTPException(status_code=401, detail="Zalo channel is inactive")

        if x_zevent_signature:
            config = channel.config if isinstance(channel.config, dict) else {}
            oa_secret_key = config.get("oa_secret_key")
            if not oa_secret_key and config.get("oa_secret_key_encrypted"):
                try:
                    oa_secret_key = decrypt_token(config["oa_secret_key_encrypted"], settings.CHANNEL_ENCRYPTION_KEY)
                except (ValueError, TypeError):
                    oa_secret_key = ""
            app_id = config.get("oa_app_id") or config.get("app_id") or payload.get("app_id")
            if not verify_zalo_oa_signature(
                raw_body,
                signature=x_zevent_signature,
                app_id=str(app_id or ""),
                timestamp=str(payload.get("timestamp") or ""),
                oa_secret_key=str(oa_secret_key or ""),
            ):
                raise HTTPException(status_code=401, detail="Invalid Zalo OA webhook signature")

        adapter = get_channel_adapter("zalo")
        access_token = None
        if channel.access_token_encrypted:
            try:
                access_token = decrypt_token(channel.access_token_encrypted, settings.CHANNEL_ENCRYPTION_KEY)
            except (ValueError, TypeError):
                logger.warning("Unable to decrypt Zalo profile token", exc_info=True)
        events = adapter.parse_events(payload, external_account_id=channel.external_account_id)
        accepted_events = ingest_normalized_events(db, events)
        processed = 0
        for event in accepted_events:
            try:
                created_messages = []
                for item in event.messages:
                    profile = item.metadata or {}
                    if not profile.get("avatar_url") and access_token:
                        try:
                            profile = {**profile, **adapter.fetch_user_profile(user_id=item.sender_external_id, access_token=access_token)}
                        except Exception:
                            logger.info("Zalo profile enrichment unavailable", exc_info=True)
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
                            "channel_id": event.channel_id or channel.id,
                        },
                    )
                    if not isinstance(saved, dict):
                        raise RuntimeError("Zalo message could not be persisted")
                    if saved.get("_created", True):
                        processed += 1
                        created_messages.append(saved)
                mark_channel_event_processed(db, event)
            except Exception as exc:
                db.rollback()
                mark_channel_event_failed(db, event, exc)
                logger.error("Webhook persistence failed: provider=zalo event_id=%s error_type=%s", event.external_event_id, type(exc).__name__)
                raise HTTPException(status_code=500, detail="Unable to persist Zalo webhook") from exc
            for saved in created_messages:
                await manager.broadcast({
                    "type": "message_created",
                    "conversation_id": saved.get("conversation_id"),
                    "message": {key: value for key, value in saved.items() if key != "_created"},
                }, business_id=int(saved.get("business_id") or event.business_id))
        return {"status": "received", "processed": processed}
