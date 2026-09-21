"""Telegram webhook ingress routed through the platform registry."""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.database.platform_session import get_platform_db
from app.database.tenant_session import tenant_session
from app.integrations import get_channel_adapter
from app.models.channel import Channel
from app.services.channel_event_service import (
    ingest_normalized_events,
    mark_channel_event_failed,
    mark_channel_event_processed,
)
from app.services.message_service import process_and_save_message
from app.services.realtime import manager
from app.tenancy.registry import resolve_webhook_route


router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("")
async def receive_telegram_webhook(
    payload: dict,
    request: Request,
    platform_db: Session = Depends(get_platform_db),
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    """Verify the route in platform DB, then write only to that shop schema."""
    if not x_telegram_bot_api_secret_token:
        raise HTTPException(status_code=401, detail="Invalid Telegram webhook secret")
    try:
        route = resolve_webhook_route(platform_db, "telegram", x_telegram_bot_api_secret_token)
    except RuntimeError:
        route = None
    if route is None:
        raise HTTPException(status_code=401, detail="Invalid Telegram webhook secret")

    with tenant_session(route.schema_name) as db:
        channel = db.get(Channel, route.channel_id)
        if channel is None or channel.channel_type != "telegram" or channel.status != "active":
            raise HTTPException(status_code=401, detail="Telegram channel is inactive")
        adapter = get_channel_adapter("telegram")
        events = adapter.parse_events(payload, external_account_id=channel.external_account_id)
        accepted = ingest_normalized_events(db, events)
        processed = 0
        for event in accepted:
            try:
                created_messages = []
                for item in event.messages:
                    profile = item.metadata or {}
                    saved = process_and_save_message(db=db, message={
                        "channel": event.provider.value,
                        "external_account_id": event.external_account_id,
                        "external_user_id": item.sender_external_id,
                        "external_message_id": item.external_message_id,
                        "content": item.text,
                        "name": profile.get("display_name"),
                        "display_name": profile.get("display_name"),
                        "username": profile.get("username"),
                        "avatar_url": profile.get("avatar_url"),
                        "media_type": item.message_type.value,
                        "media_url": item.attachments[0].url if item.attachments else None,
                        "attachments": [attachment.model_dump(mode="json") for attachment in item.attachments],
                        "raw_payload": event.raw_payload,
                        "business_id": event.business_id,
                        "channel_id": event.channel_id or channel.id,
                    })
                    if not isinstance(saved, dict):
                        raise RuntimeError("Telegram message could not be persisted")
                    if saved.get("_created", True):
                        processed += 1
                        created_messages.append(saved)
                mark_channel_event_processed(db, event)
            except Exception as exc:
                db.rollback()
                mark_channel_event_failed(db, event, exc)
                logger.error("Webhook persistence failed: provider=telegram event_id=%s error_type=%s", event.external_event_id, type(exc).__name__)
                raise HTTPException(status_code=500, detail="Unable to persist Telegram webhook") from exc
            for saved in created_messages:
                await manager.broadcast({
                    "type": "message_created",
                    "conversation_id": saved.get("conversation_id"),
                    "message": {key: value for key, value in saved.items() if key != "_created"},
                }, business_id=int(saved.get("business_id") or event.business_id))
        return {"status": "received", "processed": processed}
