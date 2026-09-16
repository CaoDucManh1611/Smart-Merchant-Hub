"""Facebook Messenger webhook routed through the platform route registry."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.platform_session import get_platform_db
from app.database.tenant_session import tenant_session
from app.integrations import get_channel_adapter
from app.services.channel_event_service import (
    ingest_normalized_events,
    mark_channel_event_failed,
    mark_channel_event_processed,
)
from app.services.message_service import process_and_save_message
from app.services.realtime import manager
from app.tenancy.registry import resolve_webhook_route
from app.tenancy.webhook import verify_meta_signature


router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
async def verify_facebook_webhook(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_verify_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.FACEBOOK_VERIFY_TOKEN:
        return PlainTextResponse(content=hub_challenge, status_code=200)
    raise HTTPException(status_code=403, detail="Invalid Facebook verify token")


async def _receive_meta_webhook(
    provider: str,
    payload: dict,
    request: Request,
    platform_db: Session,
    signature: str | None,
) -> dict:
    """Verify once, then process each account in its own tenant transaction."""
    if settings.ENVIRONMENT == "production" and not settings.META_APP_SECRET:
        raise HTTPException(status_code=500, detail="META_APP_SECRET is required")
    if settings.META_APP_SECRET and not verify_meta_signature(
        await request.body(), signature, settings.META_APP_SECRET
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    events = get_channel_adapter(provider).parse_events(payload)
    grouped: dict[tuple[int, str], list] = {}
    for event in events:
        route = resolve_webhook_route(platform_db, provider, event.external_account_id)
        if route is None:
            # Do not scan tenant tables or infer a default shop from payload.
            continue
        grouped.setdefault((route.business_id, route.schema_name), []).append(event)

    processed = 0
    for (_business_id, schema_name), tenant_events in grouped.items():
        with tenant_session(schema_name) as db:
            accepted = ingest_normalized_events(db, tenant_events)
            for event in accepted:
                try:
                    created_messages = []
                    for item in event.messages:
                        saved = process_and_save_message(
                            db=db,
                            message={
                                "channel": event.provider.value,
                                "external_user_id": item.sender_external_id,
                                "external_message_id": item.external_message_id,
                                "content": item.text,
                                "media_type": item.message_type.value,
                                "media_url": item.attachments[0].url if item.attachments else None,
                                "attachments": [a.model_dump(mode="json") for a in item.attachments],
                                "raw_payload": event.raw_payload,
                                "external_account_id": event.external_account_id,
                                "business_id": event.business_id,
                                "channel_id": event.channel_id,
                            },
                        )
                        if not isinstance(saved, dict):
                            raise RuntimeError("Meta message could not be persisted")
                        if saved.get("_created", True):
                            processed += 1
                            created_messages.append(saved)
                    mark_channel_event_processed(db, event)
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    mark_channel_event_failed(db, event, exc)
                    logger.error(
                        "Meta webhook persistence failed: provider=%s event_type=%s error_type=%s",
                        provider,
                        event.event_type,
                        type(exc).__name__,
                    )
                    raise HTTPException(status_code=500, detail="Unable to persist Meta webhook") from exc
                for saved in created_messages:
                    await manager.broadcast({
                        "type": "message_created",
                        "conversation_id": saved.get("conversation_id"),
                        "message": {k: v for k, v in saved.items() if k != "_created"},
                    })
    if events and not grouped:
        # Unknown or already-processed deliveries are acknowledged so
        # providers do not retry indefinitely. No tenant data is touched.
        return {"status": "received", "processed": 0}
    return {"status": "received", "processed": processed}


@router.post("")
async def receive_facebook_webhook(
    payload: dict,
    request: Request,
    platform_db: Session = Depends(get_platform_db),
    x_hub_signature_256: str | None = Header(default=None),
):
    return await _receive_meta_webhook(
        "facebook", payload, request, platform_db, x_hub_signature_256
    )
