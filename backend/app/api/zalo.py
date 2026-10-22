"""Zalo Bot Creator/Official Account webhook ingress."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.platform_session import get_platform_db
from app.database.tenant_session import tenant_session
from app.integrations import get_channel_adapter
from app.models.channel import Channel, ChannelEvent
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
_ZALO_HISTORY_PAGE_SIZE = 10
_ZALO_HISTORY_MAX_PAGES_PER_RUN = 200
_ZALO_HISTORY_PROCESSING_LEASE_SECONDS = 900


def _zalo_history_time(value: object) -> datetime | None:
    try:
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _sync_zalo_oa_user_history(
    schema_name: str,
    channel_id: int,
    business_id: int,
    user_id: str,
    excluded_message_ids: list[str],
) -> None:
    """Resume one OA user's history import; imported records never trigger automation."""
    user_id = str(user_id or "").strip()[:255]
    if not user_id:
        return
    marker_id = f"history-sync:zalo:{user_id}"[:255]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with tenant_session(schema_name) as db:
        channel = db.get(Channel, channel_id)
        if channel is None or channel.status != "active" or channel.channel_type != "zalo":
            return
        config = channel.config if isinstance(channel.config, dict) else {}
        provider = str(config.get("provider") or "").strip().lower()
        provider_account = config.get("provider_account") if isinstance(config.get("provider_account"), dict) else {}
        mode = str(provider_account.get("mode") or "").strip().lower()
        if provider not in {"oa", "zalo_oa", "official_account"} and mode not in {"oa", "official_account", "zalo_oa"}:
            return
        if not channel.access_token_encrypted:
            return
        try:
            access_token = decrypt_token(channel.access_token_encrypted, settings.CHANNEL_ENCRYPTION_KEY)
        except (ValueError, TypeError):
            return

        marker = db.scalar(select(ChannelEvent).where(
            ChannelEvent.channel_id == channel_id,
            ChannelEvent.external_event_id == marker_id,
        ).with_for_update())
        if marker and marker.status == "processed":
            return
        if marker and marker.status == "failed" and marker.received_at:
            age = (now - marker.received_at.replace(tzinfo=None)).total_seconds()
            if age < 3600:
                return
        if marker and marker.status == "processing" and marker.received_at:
            age = (now - marker.received_at.replace(tzinfo=None)).total_seconds()
            if age < _ZALO_HISTORY_PROCESSING_LEASE_SECONDS:
                return
        if marker is None:
            marker = ChannelEvent(
                channel_id=channel_id,
                event_type="history_sync",
                external_event_id=marker_id,
                payload={"user_id": user_id, "offset": 0},
                status="processing",
                received_at=now,
            )
            try:
                with db.begin_nested():
                    db.add(marker)
                    db.flush()
            except IntegrityError:
                db.rollback()
                return
        marker.status = "processing"
        marker.error_message = None
        marker.received_at = now
        db.commit()

        offset = max(0, int((marker.payload or {}).get("offset") or 0))
        excluded = {str(value).rsplit(":", 1)[-1] for value in excluded_message_ids}
        adapter = get_channel_adapter("zalo")
        for _ in range(_ZALO_HISTORY_MAX_PAGES_PER_RUN):
            try:
                records = adapter.fetch_conversation_history(
                    user_id=user_id,
                    access_token=access_token,
                    offset=offset,
                    count=_ZALO_HISTORY_PAGE_SIZE,
                )
            except Exception as exc:
                marker.status = "failed"
                marker.error_message = f"history_fetch_failed:{type(exc).__name__}"[:1000]
                marker.received_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.commit()
                logger.warning("Zalo OA history import paused: error_type=%s", type(exc).__name__)
                return

            for record in records:
                source_id = str(record.get("message_id") or "").strip()
                if not source_id or source_id in excluded:
                    continue
                source = str(record.get("src") if record.get("src") is not None else "1").strip()
                direction = "inbound" if source == "1" else "outbound"
                message_type = str(record.get("type") or "text").strip().lower()
                media_type = {
                    "photo": "image", "gif": "image", "voice": "audio", "sticker": "sticker",
                }.get(message_type)
                if message_type not in {"text", "photo", "gif", "voice", "sticker", "link", "links", "location"}:
                    continue
                content = str(record.get("message") or record.get("description") or "").strip()
                if not content:
                    content = f"[{media_type or message_type}]"
                profile_prefix = "from" if direction == "inbound" else "to"
                try:
                    saved = process_and_save_message(
                        db=db,
                        history_import=True,
                        message={
                            "channel": "zalo",
                            "external_account_id": channel.external_account_id,
                            "external_user_id": user_id,
                            "external_message_id": f"zalo:{channel.external_account_id}:{source_id}"[:255],
                            "direction": direction,
                            "content": content[:10000],
                            "name": str(record.get(f"{profile_prefix}_display_name") or "")[:255] or None,
                            "display_name": str(record.get(f"{profile_prefix}_display_name") or "")[:255] or None,
                            "avatar_url": str(record.get(f"{profile_prefix}_avatar") or "")[:2000] or None,
                            "media_type": media_type,
                            "media_url": str(record.get("url") or record.get("thumb") or "")[:2000] or None,
                            "received_at": _zalo_history_time(record.get("time")),
                            "raw_payload": {
                                "threadId": user_id,
                                "history_import": True,
                                "zalo_message_id": source_id,
                            },
                            "business_id": business_id,
                            "channel_id": channel_id,
                        },
                    )
                    if not isinstance(saved, dict):
                        raise RuntimeError("message_persistence_failed")
                except Exception as exc:
                    db.rollback()
                    marker = db.get(ChannelEvent, marker.id)
                    marker.status = "failed"
                    marker.error_message = f"history_persist_failed:{type(exc).__name__}"[:1000]
                    marker.received_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    db.commit()
                    logger.warning("Zalo OA history persistence paused: error_type=%s", type(exc).__name__)
                    return

            offset += len(records)
            marker.payload = {"user_id": user_id, "offset": offset}
            marker.received_at = datetime.now(timezone.utc).replace(tzinfo=None)
            if len(records) < _ZALO_HISTORY_PAGE_SIZE:
                marker.status = "processed"
                marker.processed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            if marker.status == "processed":
                logger.info("Zalo OA history imported: messages=%s", offset)
                return
        # Leave the last committed offset in ``processing`` state. A later
        # webhook can resume it after the lease instead of rescanning from zero.


@router.post("")
async def receive_zalo_webhook(
    request: Request,
    payload: dict,
    background_tasks: BackgroundTasks,
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
            except (ValueError, TypeError) as exc:
                logger.warning("Unable to decrypt Zalo profile token: error_type=%s", type(exc).__name__)
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
                        except Exception as exc:
                            logger.info("Zalo profile enrichment unavailable: error_type=%s", type(exc).__name__)
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
            if x_zevent_signature and access_token:
                for item in event.messages:
                    background_tasks.add_task(
                        _sync_zalo_oa_user_history,
                        route.schema_name,
                        int(channel.id),
                        int(event.business_id),
                        item.sender_external_id,
                        [message.external_message_id for message in event.messages],
                    )
        return {"status": "received", "processed": processed}
