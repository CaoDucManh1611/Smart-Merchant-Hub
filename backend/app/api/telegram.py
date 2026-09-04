from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.integrations import get_channel_adapter
from app.services.channel_event_service import ingest_normalized_events
from app.services.message_service import process_and_save_message
from app.services.realtime import manager
from app.tenancy.webhook import resolve_telegram_channel

router = APIRouter()


@router.post("")
async def receive_telegram_webhook(
    payload: dict,
    request: Request,
    db: Session = Depends(get_db),
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    """Receive Telegram updates and persist them through the common inbox."""
    channel = resolve_telegram_channel(db, x_telegram_bot_api_secret_token)
    if channel is None:
        raise HTTPException(status_code=401, detail="Invalid Telegram webhook secret")

    adapter = get_channel_adapter("telegram")
    events = adapter.parse_events(payload, external_account_id=channel.external_account_id)
    accepted = ingest_normalized_events(db, events)
    processed = 0
    for event in accepted:
        for item in event.messages:
            saved = process_and_save_message(db=db, message={
                "channel": event.provider.value,
                "external_account_id": event.external_account_id,
                "external_user_id": item.sender_external_id,
                "external_message_id": item.external_message_id,
                "content": item.text,
                "media_type": item.message_type.value,
                "media_url": item.attachments[0].url if item.attachments else None,
                "attachments": [attachment.model_dump(mode="json") for attachment in item.attachments],
                "raw_payload": event.raw_payload,
                "business_id": event.business_id,
                "channel_id": event.channel_id,
            })
            if isinstance(saved, dict):
                processed += 1
                await manager.broadcast({"type": "message_created", "conversation_id": saved.get("conversation_id"), "message": saved})
    return {"status": "received", "processed": processed}
