"""Pairing and inbound messages for local TikTok/Shopee connectors."""

from __future__ import annotations

import hashlib
import hmac
from io import BytesIO
import json
import re
import secrets
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from zipfile import ZIP_STORED, ZipFile

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth.dependencies import require_admin_access
from app.core.config import settings
from app.database.platform_session import get_platform_db
from app.database.tenant_session import tenant_session
from app.models.business import User
from app.models.channel import Channel
from app.models.customer_identity import CustomerIdentity
from app.models.customer import Customer
from app.models.sales import Order, OrderItem, Product
from app.models.platform_control import PlatformBusiness, TenantRegistry
from app.services.audit_service import record_audit
from app.services.channel_credentials import decrypt_token, encrypt_token
from app.services.customer_profile import normalize_avatar_url
from app.services.message_service import process_and_save_message
from app.services.realtime import manager
from app.services.quota_service import QuotaExceededError, reserve_quota
from app.tenancy.schema import schema_name_for, validate_schema_name

router = APIRouter(tags=["Local channel connectors"])
_SUPPORTED = {"tiktok", "shopee"}
_CHAT_SUPPORTED = _SUPPORTED | {"facebook", "instagram"}
_CODE_RE = re.compile(r"^(PAIR|CONN)\.(tiktok|shopee|facebook|instagram)\.(\d+)\.(\d+)\.([A-Za-z0-9_-]{12,})$")


class PairConnectorRequest(BaseModel):
    pairing_code: str = Field(min_length=24, max_length=200)
    execution_mode: Literal["local", "server"] = "local"


class ServerViewerInput(BaseModel):
    action: Literal["click", "type", "press", "scroll"]
    x: int | None = Field(default=None, ge=0, le=10000)
    y: int | None = Field(default=None, ge=0, le=10000)
    text: str | None = Field(default=None, max_length=2000)
    key: str | None = Field(default=None, max_length=32)
    delta_y: int | None = Field(default=None, ge=-2000, le=2000)


class ConnectorHeartbeatRequest(BaseModel):
    state: str = Field(default="online", pattern="^(online|error)$")
    error_code: str | None = Field(default=None, max_length=80, pattern="^[a-zA-Z0-9_.-]+$")
    retry_ack_id: str | None = Field(default=None, max_length=80, pattern="^[A-Za-z0-9_-]+$")


class ConnectorOrderItem(BaseModel):
    external_product_id: str | None = Field(default=None, max_length=255)
    sku: str | None = Field(default=None, max_length=80)
    name: str = Field(min_length=1, max_length=255)
    quantity: int = Field(ge=1, le=100000)
    unit_price: Decimal = Field(ge=0)


class ConnectorOrder(BaseModel):
    external_order_id: str = Field(min_length=1, max_length=255)
    buyer_id: str | None = Field(default=None, max_length=255)
    source_status: str = Field(default="unknown", max_length=80)
    total_amount: Decimal = Field(ge=0)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    items: list[ConnectorOrderItem] = Field(min_length=1, max_length=100)


class ConnectorOrderBatch(BaseModel):
    orders: list[ConnectorOrder] = Field(min_length=1, max_length=100)


def _code_parts(value: str, kind: str, channel_type: str | None = None) -> tuple[str, int, int, str]:
    match = _CODE_RE.fullmatch(str(value or "").strip())
    if not match or match.group(1) != kind or (channel_type and match.group(2) != channel_type):
        raise HTTPException(status_code=401, detail="Mã ghép nối không hợp lệ.")
    try:
        business_id, channel_id = int(match.group(3)), int(match.group(4))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Mã ghép nối không hợp lệ.") from exc
    return match.group(2), business_id, channel_id, match.group(5)


def _tenant_schema(platform_db: Session, business_id: int) -> str:
    business = platform_db.scalar(
        select(PlatformBusiness).where(
            PlatformBusiness.id == business_id,
            PlatformBusiness.status == "active",
        )
    )
    if business is None:
        raise HTTPException(status_code=404, detail="Shop không tồn tại hoặc đã ngừng hoạt động.")
    registry = platform_db.scalar(
        select(TenantRegistry).where(TenantRegistry.business_id == business_id)
    )
    if registry is not None and registry.state not in {"active", "ready"}:
        raise HTTPException(status_code=423, detail="Không gian shop chưa sẵn sàng.")
    return validate_schema_name(
        str(registry.schema_name) if registry is not None else schema_name_for(business_id)
    )


@router.post("/channels/pair")
def pair_local_connector(
    payload: PairConnectorRequest,
    response: Response,
    platform_db: Session = Depends(get_platform_db),
):
    """Exchange a one-time pairing code for local or server-managed execution."""

    response.headers["Cache-Control"] = "no-store"
    channel_type, business_id, channel_id, _nonce = _code_parts(payload.pairing_code, "PAIR")
    if payload.execution_mode == "server":
        _require_server_agent()
    schema = _tenant_schema(platform_db, business_id)
    supplied_hash = hashlib.sha256(payload.pairing_code.strip().encode("utf-8")).hexdigest()

    with tenant_session(schema) as tenant_db:
        channel = tenant_db.scalar(
            select(Channel)
            .where(
                Channel.id == channel_id,
                Channel.business_id == business_id,
                Channel.channel_type == channel_type,
                Channel.status.in_(("active", "pending_pairing")),
            )
            .with_for_update()
        )
        config = channel.config if channel and isinstance(channel.config, dict) else {}
        expected_hash = str(config.get("pairing_code_hash") or "")
        expires_at = int(config.get("pairing_code_expires_at") or 0)
        if not channel or not expected_hash or not hmac.compare_digest(expected_hash, supplied_hash):
            raise HTTPException(status_code=401, detail="Pairing code đã dùng hoặc không đúng.")
        if expires_at <= time.time():
            raise HTTPException(status_code=410, detail="Pairing code đã hết hạn. Hãy tạo mã mới trong Liên kết mạng xã hội.")
        try:
            connector_token = decrypt_token(
                str(config.get("pending_connector_token_encrypted") or ""),
                settings.CHANNEL_ENCRYPTION_KEY,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Không thể đọc cấu hình connector của shop.") from exc
        _code_parts(connector_token, "CONN", channel_type)
        channel.access_token_encrypted = encrypt_token(connector_token, settings.CHANNEL_ENCRYPTION_KEY)
        channel.access_token = None
        if channel.status == "pending_pairing":
            try:
                reserve_quota(platform_db, business_id, "connected_channels")
            except QuotaExceededError as exc:
                raise HTTPException(status_code=429, detail=exc.detail) from exc
            channel.status = "active"
            channel.connected_at = datetime.now(timezone.utc).replace(tzinfo=None)
        config = dict(config)
        config.pop("pairing_code_hash", None)
        config.pop("pairing_code_expires_at", None)
        config.pop("pending_connector_token_encrypted", None)
        config.pop("webhook_secret", None)
        config.pop("webhook_secret_encrypted", None)
        config.pop("bridge_control_url", None)
        config["connector_paired_at"] = int(time.time())
        if payload.execution_mode == "server":
            viewer_ticket = secrets.token_urlsafe(32)
            config["connector_execution_mode"] = "server"
            config["server_viewer_ticket_hash"] = hashlib.sha256(viewer_ticket.encode("utf-8")).hexdigest()
            config["server_viewer_ticket_expires_at"] = int(time.time()) + max(
                600, min(int(settings.SERVER_CONNECTOR_VIEWER_TICKET_TTL_SECONDS or 14400), 86400)
            )
            config["connector_status"] = "starting"
        else:
            config["connector_execution_mode"] = "local"
            for key in ("server_viewer_ticket_hash", "server_viewer_ticket_expires_at"):
                config.pop(key, None)
        channel.config = config
        tenant_db.flush()

    platform_db.commit()

    if payload.execution_mode == "server":
        return {
            "channel_type": channel_type,
            "business_id": business_id,
            "channel_id": channel_id,
            "server_managed": True,
            "viewer_ticket": viewer_ticket,
            "incoming_endpoint": f"/api/channels/{channel_type}/incoming",
        }
    return {
        "channel_type": channel_type,
        "connector_token": connector_token,
        "incoming_endpoint": f"/api/channels/{channel_type}/incoming",
    }


def _server_agent_headers() -> dict[str, str]:
    token = str(settings.SERVER_CONNECTOR_AGENT_TOKEN or "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="Server connector agent chưa được cấu hình.")
    return {"X-Server-Connector-Agent-Token": token}


def _require_server_agent() -> str:
    agent_url = str(settings.SERVER_CONNECTOR_AGENT_URL or "").strip().rstrip("/")
    if not agent_url:
        raise HTTPException(status_code=503, detail="Server connector agent chưa được cấu hình.")
    try:
        parsed = urlsplit(agent_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("invalid agent URL")
        health = httpx.get(f"{agent_url}/health", headers=_server_agent_headers(), timeout=3)
        if health.status_code != 200:
            raise HTTPException(status_code=503, detail="Windows connector agent chưa sẵn sàng.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Không kết nối được Windows connector agent.") from exc
    return agent_url


def _authorized_server_agent(x_server_connector_agent_token: str | None) -> None:
    expected = str(settings.SERVER_CONNECTOR_AGENT_TOKEN or "").strip()
    if not expected or not x_server_connector_agent_token or not hmac.compare_digest(
        expected, x_server_connector_agent_token.strip()
    ):
        raise HTTPException(status_code=401, detail="Server agent không được xác thực.")


@router.get("/channels/server-managed/active")
def list_server_managed_connectors(
    x_server_connector_agent_token: str | None = Header(default=None, alias="X-Server-Connector-Agent-Token"),
    platform_db: Session = Depends(get_platform_db),
):
    """Private agent poll endpoint. Connector tokens are returned only over the configured secret channel."""
    _authorized_server_agent(x_server_connector_agent_token)
    active: list[dict] = []
    businesses = platform_db.scalars(
        select(PlatformBusiness).where(PlatformBusiness.status == "active")
    ).all()
    for business in businesses:
        business_id = int(business.id)
        try:
            schema = _tenant_schema(platform_db, business_id)
            with tenant_session(schema) as tenant_db:
                channels = tenant_db.scalars(
                    select(Channel).where(
                        Channel.business_id == business_id,
                        Channel.status == "active",
                    )
                ).all()
                for channel in channels:
                    config = channel.config if isinstance(channel.config, dict) else {}
                    channel_type = str(channel.channel_type or "")
                    if (
                        channel_type not in _CHAT_SUPPORTED
                        or config.get("connector_execution_mode") != "server"
                        or config.get("provider") != f"{channel_type}_local_connector"
                        or not channel.access_token_encrypted
                    ):
                        continue
                    try:
                        connector_token = decrypt_token(
                            channel.access_token_encrypted, settings.CHANNEL_ENCRYPTION_KEY
                        )
                    except Exception:
                        continue
                    active.append({
                        "business_id": business_id,
                        "channel_id": int(channel.id),
                        "channel_type": channel_type,
                        "connector_token": connector_token,
                    })
        except HTTPException:
            continue
    return {"connectors": active}


def _server_viewer_channel(
    business_id: int,
    channel_type: str,
    channel_id: int,
    authorization: str | None,
    platform_db: Session,
) -> tuple[str, dict]:
    if channel_type not in _CHAT_SUPPORTED:
        raise HTTPException(status_code=404, detail="Kênh không hỗ trợ server viewer.")
    scheme, _, ticket = str(authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not ticket.strip():
        raise HTTPException(status_code=401, detail="Thiếu viewer ticket.")
    schema = _tenant_schema(platform_db, business_id)
    with tenant_session(schema) as tenant_db:
        channel = tenant_db.scalar(select(Channel).where(
            Channel.id == channel_id,
            Channel.business_id == business_id,
            Channel.channel_type == channel_type,
            Channel.status == "active",
        ))
        config = channel.config if channel and isinstance(channel.config, dict) else {}
        expected = str(config.get("server_viewer_ticket_hash") or "")
        supplied = hashlib.sha256(ticket.strip().encode("utf-8")).hexdigest()
        expires_at = int(config.get("server_viewer_ticket_expires_at") or 0)
        if (
            not channel
            or config.get("connector_execution_mode") != "server"
            or not expected
            or expires_at <= time.time()
            or not hmac.compare_digest(expected, supplied)
        ):
            raise HTTPException(status_code=401, detail="Viewer ticket hết hạn hoặc không hợp lệ.")
        return schema, dict(config)


@router.get("/channels/{business_id}/{channel_type}/{channel_id}/server-session/screenshot")
def get_server_connector_screenshot(
    business_id: int,
    channel_type: str,
    channel_id: int,
    authorization: str | None = Header(default=None, alias="Authorization"),
    platform_db: Session = Depends(get_platform_db),
):
    _server_viewer_channel(business_id, channel_type, channel_id, authorization, platform_db)
    agent_url = _require_server_agent()
    try:
        response = httpx.get(
            f"{agent_url}/internal/channels/{business_id}/{channel_type}/{channel_id}/screenshot",
            headers=_server_agent_headers(), timeout=15,
        )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Không đọc được màn hình Edge trên server.") from exc
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Windows agent chưa có màn hình đăng nhập sẵn sàng.")
    return Response(content=response.content, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/channels/{business_id}/{channel_type}/{channel_id}/server-session/input")
def send_server_connector_input(
    business_id: int,
    channel_type: str,
    channel_id: int,
    payload: ServerViewerInput,
    authorization: str | None = Header(default=None, alias="Authorization"),
    platform_db: Session = Depends(get_platform_db),
):
    _server_viewer_channel(business_id, channel_type, channel_id, authorization, platform_db)
    agent_url = _require_server_agent()
    try:
        response = httpx.post(
            f"{agent_url}/internal/channels/{business_id}/{channel_type}/{channel_id}/input",
            json=payload.model_dump(exclude_none=True), headers=_server_agent_headers(), timeout=10,
        )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Không gửi được thao tác tới Edge trên server.") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="Windows agent từ chối thao tác trên phiên đăng nhập.")
    return {"status": "accepted"}


def _connector_channel(
    channel_type: str,
    authorization: str | None,
    platform_db: Session,
) -> tuple[int, int]:
    scheme, _, token = str(authorization or "").partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Thiếu connector token.")
    token = token.strip()
    parsed_type, business_id, channel_id, _nonce = _code_parts(token, "CONN", channel_type)
    schema = _tenant_schema(platform_db, business_id)

    with tenant_session(schema) as tenant_db:
        channel = tenant_db.scalar(
            select(Channel).where(
                Channel.id == channel_id,
                Channel.business_id == business_id,
                Channel.channel_type == parsed_type,
                Channel.status == "active",
            )
        )
        if channel is None:
            raise HTTPException(status_code=401, detail="Connector đã bị ngắt hoặc không còn hợp lệ.")
        try:
            expected = decrypt_token(
                str(channel.access_token_encrypted or ""),
                settings.CHANNEL_ENCRYPTION_KEY,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Không thể xác thực connector của shop.") from exc
        if not hmac.compare_digest(expected, token):
            raise HTTPException(status_code=401, detail="Connector token không hợp lệ.")
    return business_id, channel_id


def _marketplace_order_number(channel_type: str, shop_id: str, external_order_id: str) -> str:
    seed = f"{channel_type}|{shop_id}|{external_order_id}".encode("utf-8")
    prefix = "SHP" if channel_type == "shopee" else "TTS"
    return f"{prefix}-{hashlib.sha256(seed).hexdigest()[:32]}"


def _as_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


@router.post("/channels/{channel_type}/orders")
def receive_local_connector_orders(
    channel_type: str,
    payload: ConnectorOrderBatch,
    authorization: str | None = Header(default=None, alias="Authorization"),
    platform_db: Session = Depends(get_platform_db),
):
    """Import orders read from the seller UI as safe CRM drafts, idempotently."""
    if channel_type not in _SUPPORTED:
        raise HTTPException(status_code=404, detail="Kênh connector không được hỗ trợ.")
    if len(payload.model_dump_json().encode("utf-8")) > 1_500_000:
        raise HTTPException(status_code=413, detail="Lô đơn hàng vượt quá dung lượng cho phép.")

    business_id, channel_id = _connector_channel(channel_type, authorization, platform_db)
    schema = _tenant_schema(platform_db, business_id)
    created = updated = 0
    with tenant_session(schema) as tenant_db:
        channel = tenant_db.get(Channel, channel_id)
        if (
            not channel
            or channel.business_id != business_id
            or channel.channel_type != channel_type
            or channel.status != "active"
        ):
            raise HTTPException(status_code=401, detail="Kênh connector đã bị ngắt hoặc không còn hợp lệ.")

        shop_id = str(channel.external_account_id or channel.id)[:255]
        for imported in payload.orders:
            order_number = _marketplace_order_number(channel_type, shop_id, imported.external_order_id)
            source_metadata = {
                "marketplace_source": channel_type,
                "marketplace_shop_id": shop_id,
                "external_order_id": imported.external_order_id,
                "external_status": imported.source_status,
                "external_created_at": imported.created_at.isoformat() if imported.created_at else None,
                "external_updated_at": imported.updated_at.isoformat() if imported.updated_at else None,
                "last_marketplace_sync_at": datetime.now(timezone.utc).isoformat(),
            }
            existing = tenant_db.scalar(
                select(Order).where(
                    Order.business_id == business_id,
                    Order.order_number == order_number,
                )
            )
            if existing is not None:
                existing.metadata_ = {**(existing.metadata_ or {}), **source_metadata}
                updated += 1
                continue

            buyer_id = str(imported.buyer_id or "").strip()
            # If the seller UI does not expose a stable buyer ID, attach
            # orders to one shop-scoped placeholder instead of creating one
            # fake CRM customer per order.
            external_user_id = buyer_id or "marketplace-orders"
            identity = None
            if buyer_id:
                identity = tenant_db.scalar(
                    select(CustomerIdentity).where(
                        CustomerIdentity.business_id == business_id,
                        CustomerIdentity.channel == channel_type,
                        CustomerIdentity.external_account_id == shop_id,
                        CustomerIdentity.external_user_id == buyer_id,
                    )
                )
            customer = identity.customer if identity is not None else None
            if customer is None:
                customer_key = f"{shop_id}:{external_user_id}"[:255]
                customer = tenant_db.scalar(
                    select(Customer).where(
                        Customer.business_id == business_id,
                        Customer.channel == channel_type,
                        Customer.external_user_id == customer_key,
                    )
                )
                if customer is None:
                    customer = Customer(
                        business_id=business_id,
                        channel=channel_type,
                        external_user_id=customer_key,
                        name=f"Khách {channel_type.title()}",
                    )
                    tenant_db.add(customer)
                    tenant_db.flush()
                if buyer_id and identity is None:
                    tenant_db.add(CustomerIdentity(
                        business_id=business_id,
                        customer_id=customer.id,
                        channel=channel_type,
                        external_account_id=shop_id,
                        external_user_id=external_user_id,
                    ))

            order_items = []
            computed_total = Decimal("0")
            for line in imported.items:
                product = None
                external_sku = str(line.sku or "").strip()
                if external_sku:
                    product = tenant_db.scalar(
                        select(Product).where(
                            Product.business_id == business_id,
                            Product.sku == external_sku,
                        )
                    )
                if product is None:
                    product_key = line.external_product_id or external_sku or line.name
                    product_hash = hashlib.sha256(
                        f"{channel_type}|{shop_id}|{product_key}".encode("utf-8")
                    ).hexdigest()[:32]
                    placeholder_sku = f"EXT-{channel_type[:2].upper()}-{product_hash}"
                    product = tenant_db.scalar(
                        select(Product).where(
                            Product.business_id == business_id,
                            Product.sku == placeholder_sku,
                        )
                    )
                    if product is None:
                        product = Product(
                            business_id=business_id,
                            sku=placeholder_sku,
                            name=line.name,
                            price=line.unit_price,
                            stock_quantity=0,
                            status="external",
                            metadata_={
                                "marketplace_source": channel_type,
                                "external_product_id": line.external_product_id,
                                "external_sku": external_sku,
                            },
                        )
                        tenant_db.add(product)
                        tenant_db.flush()
                line_total = line.unit_price * line.quantity
                computed_total += line_total
                order_items.append((line, product, line_total))

            order = Order(
                business_id=business_id,
                customer_id=customer.id,
                order_number=order_number,
                status="draft",
                total_amount=imported.total_amount if imported.total_amount else computed_total,
                created_at=_as_naive_utc(imported.created_at),
                metadata_=source_metadata,
            )
            tenant_db.add(order)
            tenant_db.flush()
            for line, product, line_total in order_items:
                tenant_db.add(OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    line_total=line_total,
                    product_name_snapshot=line.name,
                    sku_snapshot=line.sku or product.sku,
                ))
            created += 1
        tenant_db.commit()

    return {"status": "received", "created": created, "updated": updated, "duplicates": 0}


@router.post("/channels/{channel_type}/heartbeat")
def report_connector_heartbeat(
    channel_type: str,
    payload: ConnectorHeartbeatRequest,
    authorization: str | None = Header(default=None, alias="Authorization"),
    platform_db: Session = Depends(get_platform_db),
):
    """Record a minimal, authenticated liveness/error signal; never accept raw logs."""
    if channel_type not in _CHAT_SUPPORTED:
        raise HTTPException(status_code=404, detail="Kênh connector không được hỗ trợ.")
    business_id, channel_id = _connector_channel(channel_type, authorization, platform_db)
    schema = _tenant_schema(platform_db, business_id)
    with tenant_session(schema) as tenant_db:
        channel = tenant_db.scalar(select(Channel).where(
            Channel.id == channel_id,
            Channel.business_id == business_id,
            Channel.channel_type == channel_type,
            Channel.status == "active",
        ))
        if channel is None:
            raise HTTPException(status_code=401, detail="Connector đã bị ngắt hoặc không còn hợp lệ.")
        config = dict(channel.config) if isinstance(channel.config, dict) else {}
        now = datetime.now(timezone.utc)
        config["connector_last_seen_at"] = now.isoformat()
        config["connector_last_error_code"] = payload.error_code if payload.state == "error" else None
        config["connector_status"] = payload.state
        pending_retry_id = str(config.get("connector_retry_id") or "")
        requested_at = config.get("connector_retry_requested_at")
        if pending_retry_id and requested_at:
            try:
                requested_time = datetime.fromisoformat(str(requested_at).replace("Z", "+00:00"))
                if (now - requested_time.astimezone(timezone.utc)).total_seconds() > 300:
                    config.pop("connector_retry_id", None)
                    config.pop("connector_retry_requested_at", None)
                    pending_retry_id = ""
            except (TypeError, ValueError):
                config.pop("connector_retry_id", None)
                config.pop("connector_retry_requested_at", None)
                pending_retry_id = ""
        retry_acknowledged = bool(pending_retry_id and payload.retry_ack_id == pending_retry_id)
        if retry_acknowledged:
            config.pop("connector_retry_id", None)
            config.pop("connector_retry_requested_at", None)
        channel.config = config
        tenant_db.commit()
    result = {"status": "recorded", "connector_status": payload.state}
    if retry_acknowledged:
        result["retry_acknowledged"] = True
    elif pending_retry_id:
        result["retry_id"] = pending_retry_id
    return result


async def receive_local_connector_message(
    channel_type: str,
    payload: dict,
    authorization: str | None,
    platform_db: Session,
):
    if channel_type not in _CHAT_SUPPORTED:
        raise HTTPException(status_code=404, detail="Kênh connector không được hỗ trợ.")
    if len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")) > 262144:
        raise HTTPException(status_code=413, detail="Tin nhắn gửi lên vượt quá dung lượng cho phép.")

    business_id, channel_id = _connector_channel(channel_type, authorization, platform_db)
    # Seller Chat also emits shop/system cards. They are not customer text and
    # must not enter the conversation-turn queue or trigger an AI reply.
    message_type = str(payload.get("messageType") or payload.get("message_type") or "text").strip().lower()
    if message_type not in {"text", "image", "video", "audio", "file", "sticker"}:
        return {"status": "ignored", "processed": 0}
    sender_id = str(payload.get("authorId") or payload.get("sender_id") or payload.get("from_id") or "").strip()
    thread_id = str(payload.get("threadId") or payload.get("conversation_id") or payload.get("conv_id") or "").strip()
    content = str(payload.get("message") or payload.get("text") or "").strip()
    if not sender_id or not thread_id:
        raise HTTPException(status_code=422, detail="Tin nhắn thiếu mã khách hoặc cuộc hội thoại.")
    if not content and message_type not in {"image", "video", "audio", "file", "sticker"}:
        raise HTTPException(status_code=422, detail="Tin nhắn không có nội dung.")
    if not content:
        content = f"[{message_type}]"
    content = content[:10000]
    external_message_id = str(payload.get("messageId") or payload.get("message_id") or payload.get("id") or "").strip()
    if not external_message_id:
        seed = "|".join((channel_type, thread_id, sender_id, content, str(payload.get("createdAt") or "")))
        external_message_id = "local-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()
    external_message_id = external_message_id[:255]

    schema = _tenant_schema(platform_db, business_id)
    with tenant_session(schema) as tenant_db:
        channel = tenant_db.get(Channel, channel_id)
        if not channel or channel.business_id != business_id or channel.channel_type != channel_type or channel.status != "active":
            raise HTTPException(status_code=401, detail="Kênh đã bị ngắt hoặc không còn hợp lệ.")
        attachments = payload.get("attachments")
        if not isinstance(attachments, list):
            attachments = []
        saved = process_and_save_message(
            db=tenant_db,
            message={
                "channel": channel_type,
                "external_account_id": channel.external_account_id,
                "external_user_id": sender_id[:255],
                "external_message_id": external_message_id,
                "content": content,
                "name": str(payload.get("displayName") or payload.get("display_name") or "")[:255] or None,
                "display_name": str(payload.get("displayName") or payload.get("display_name") or "")[:255] or None,
                "username": str(payload.get("username") or "")[:255] or None,
                "avatar_url": str(payload.get("avatarUrl") or payload.get("avatar_url") or "")[:2000] or None,
                "media_type": message_type if message_type in {"image", "video", "audio", "file", "sticker"} else None,
                "media_url": str(payload.get("mediaUrl") or payload.get("media_url") or "")[:2000] or None,
                "attachments": attachments[:20],
                "raw_payload": {
                    "threadId": thread_id,
                    "message_type": message_type,
                    "created_at": str(payload.get("createdAt") or payload.get("created_at") or "")[:100],
                    "source": str(payload.get("source") or "local_connector")[:100],
                },
                "business_id": business_id,
                "channel_id": channel_id,
            },
        )
        if not isinstance(saved, dict):
            raise HTTPException(status_code=500, detail="Không thể lưu tin nhắn từ connector.")
        if saved.get("_created", True):
            await manager.broadcast(
                {
                    "type": "message_created",
                    "conversation_id": saved.get("conversation_id"),
                    "message": {key: value for key, value in saved.items() if key != "_created"},
                },
                business_id=business_id,
            )
        return {"status": "received", "processed": 1 if saved.get("_created", True) else 0}


def _history_datetime(value: object) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    text_value = str(value or "").strip()
    if not text_value:
        return None
    try:
        parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def _normalize_history_message(channel_type: str, item: object) -> dict | None:
    if not isinstance(item, dict):
        return None
    thread_id = str(item.get("threadId") or item.get("conversationId") or "").strip()[:255]
    customer_id = str(item.get("customerId") or item.get("externalUserId") or "").strip()[:255]
    message_id = str(item.get("messageId") or item.get("message_id") or "").strip()[:255]
    direction = str(item.get("direction") or "inbound").strip().lower()
    content = str(item.get("message") or item.get("text") or "").strip()[:10000]
    message_type = str(item.get("messageType") or item.get("message_type") or "text").strip().lower()
    if direction not in {"inbound", "outbound"}:
        return None
    if not thread_id or not customer_id or not message_id:
        return None
    if message_type not in {"text", "image", "video", "audio", "file", "sticker"}:
        return None
    if not content and message_type == "text":
        return None
    is_live = bool(item.get("isLive") is True and channel_type in {"facebook", "instagram"} and direction == "inbound")
    created_at_from_source = _history_datetime(item.get("createdAt") or item.get("created_at") or item.get("timestamp"))
    created_at = created_at_from_source
    if is_live and created_at is None:
        # Some Meta message bubbles have no exposed timestamp. For an item
        # explicitly identified by the live inbox watcher, use discovery time
        # so the conversation moves to the top instead of remaining stale.
        created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    return {
        "thread_id": thread_id,
        "customer_id": customer_id,
        "message_id": message_id,
        "direction": direction,
        "content": content or f"[{message_type}]",
        "message_type": message_type,
        "display_name": str(item.get("displayName") or item.get("display_name") or "")[:255] or None,
        "username": str(item.get("username") or "")[:255] or None,
        "avatar_url": str(item.get("avatarUrl") or item.get("avatar_url") or "")[:2000] or None,
        "media_url": str(item.get("mediaUrl") or item.get("media_url") or "")[:2000] or None,
        "attachments": item.get("attachments") if isinstance(item.get("attachments"), list) else [],
        "created_at": created_at,
        "created_at_from_source": created_at_from_source is not None,
        "is_live": is_live,
    }


def receive_local_connector_history(
    channel_type: str,
    payload: dict,
    authorization: str | None,
    platform_db: Session,
    *,
    collect_realtime_events: bool = False,
):
    """Persist Meta history safely; explicitly marked live messages enter automation."""
    if channel_type not in _CHAT_SUPPORTED:
        raise HTTPException(status_code=404, detail="Kênh connector không được hỗ trợ.")
    if len(json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")) > 1_500_000:
        raise HTTPException(status_code=413, detail="Lô lịch sử vượt quá dung lượng cho phép.")
    items = payload.get("messages")
    if not isinstance(items, list) or not items or len(items) > 100:
        raise HTTPException(status_code=422, detail="Mỗi lô lịch sử phải có từ 1 đến 100 tin nhắn.")
    business_id, channel_id = _connector_channel(channel_type, authorization, platform_db)
    schema = _tenant_schema(platform_db, business_id)
    imported = duplicates = skipped = 0
    realtime_events: list[tuple[int, dict]] = []
    with tenant_session(schema) as tenant_db:
        channel = tenant_db.get(Channel, channel_id)
        if not channel or channel.business_id != business_id or channel.channel_type != channel_type or channel.status != "active":
            raise HTTPException(status_code=401, detail="Kênh đã bị ngắt hoặc không còn hợp lệ.")
        for item in items:
            normalized = _normalize_history_message(channel_type, item)
            if normalized is None:
                skipped += 1
                continue
            thread_id = normalized["thread_id"]
            message_type = normalized["message_type"]
            history_import = not normalized["is_live"]
            raw_payload = {
                "threadId": thread_id,
                "message_type": message_type,
                "created_at": normalized["created_at"].isoformat() if normalized["created_at"] else None,
                "source": "meta_history_import" if history_import else "meta_live_inbox",
            }
            if history_import:
                raw_payload["history_import"] = True
            saved = process_and_save_message(
                db=tenant_db,
                history_import=history_import,
                message={
                    "channel": channel_type,
                    "external_account_id": channel.external_account_id,
                    # Outbound cards still belong to the buyer's conversation.
                    "external_user_id": normalized["customer_id"],
                    "external_message_id": normalized["message_id"],
                    "direction": normalized["direction"],
                    "content": normalized["content"],
                    "name": normalized["display_name"],
                    "display_name": normalized["display_name"],
                    "username": normalized["username"],
                    "avatar_url": normalized["avatar_url"],
                    "media_type": message_type if message_type in {"image", "video", "audio", "file", "sticker"} else None,
                    "media_url": normalized["media_url"],
                    "attachments": normalized["attachments"][:20],
                    "received_at": normalized["created_at"],
                    "raw_payload": raw_payload,
                    "business_id": business_id,
                    "channel_id": channel_id,
                },
            )
            if not isinstance(saved, dict):
                raise HTTPException(status_code=500, detail="Không thể lưu tin nhắn lịch sử.")
            if saved.get("_created", True):
                imported += 1
            else:
                if (
                    channel_type in {"facebook", "instagram"}
                    and normalized["created_at"]
                    and (not normalized["is_live"] or normalized["created_at_from_source"])
                    and saved.get("message_id")
                    and saved.get("conversation_id")
                ):
                    tenant_db.execute(
                        text("""
                            UPDATE messages
                            SET received_at = :received_at
                            WHERE id = :message_id
                              AND conversation_id = :conversation_id
                              AND channel = :channel
                        """),
                        {
                            "received_at": normalized["created_at"],
                            "message_id": int(saved["message_id"]),
                            "conversation_id": int(saved["conversation_id"]),
                            "channel": channel_type,
                        },
                    )
                    tenant_db.commit()
                duplicates += 1
                if normalized["is_live"] and saved.get("conversation_id") and saved.get("message_id"):
                    # A foreground watcher can discover a message after the
                    # background history scan already persisted it. Promote
                    # that duplicate to a bot turn; enqueue_job's stable key
                    # prevents repeated watcher polls from replying twice.
                    from app.services.conversation_turn_service import schedule_chatbot_turn

                    schedule_chatbot_turn(
                        tenant_db,
                        business_id=int(business_id),
                        conversation_id=int(saved["conversation_id"]),
                        message_id=int(saved["message_id"]),
                    )
            if normalized["is_live"] and saved.get("conversation_id"):
                # The live path already schedules automation in the message
                # service; this event only refreshes open CRM sessions.
                realtime_events.append((
                    int(business_id),
                    {
                        "type": "message_created",
                        "conversation_id": saved.get("conversation_id"),
                        "message": {key: value for key, value in saved.items() if key != "_created"},
                    },
                ))
    result = {"status": "received", "imported": imported, "duplicates": duplicates, "skipped": skipped}
    if collect_realtime_events:
        result["_realtime_events"] = realtime_events
    return result


@router.post("/channels/{channel_type}/history")
async def receive_shopee_tiktok_history(
    channel_type: str,
    payload: dict,
    authorization: str | None = Header(default=None, alias="Authorization"),
    platform_db: Session = Depends(get_platform_db),
):
    result = receive_local_connector_history(
        channel_type,
        payload,
        authorization,
        platform_db,
        collect_realtime_events=True,
    )
    for event_business_id, event in result.pop("_realtime_events", []):
        await manager.broadcast(event, business_id=event_business_id)
    return result


@router.post("/channels/facebook/incoming")
async def receive_meta_facebook_connector_message(
    payload: dict,
    authorization: str | None = Header(default=None, alias="Authorization"),
    platform_db: Session = Depends(get_platform_db),
):
    return await receive_local_connector_message("facebook", payload, authorization, platform_db)


@router.post("/channels/instagram/incoming")
async def receive_meta_instagram_connector_message(
    payload: dict,
    authorization: str | None = Header(default=None, alias="Authorization"),
    platform_db: Session = Depends(get_platform_db),
):
    return await receive_local_connector_message("instagram", payload, authorization, platform_db)


@router.post("/channels/shopee/incoming")
async def receive_shopee_connector_message(
    payload: dict,
    authorization: str | None = Header(default=None, alias="Authorization"),
    platform_db: Session = Depends(get_platform_db),
):
    return await receive_local_connector_message("shopee", payload, authorization, platform_db)


@router.post("/channels/shopee/profiles")
def sync_shopee_customer_avatars(
    payload: dict,
    authorization: str | None = Header(default=None, alias="Authorization"),
    platform_db: Session = Depends(get_platform_db),
):
    return _sync_local_connector_customer_avatars("shopee", payload, authorization, platform_db)


@router.post("/channels/tiktok/profiles")
def sync_tiktok_customer_avatars(
    payload: dict,
    authorization: str | None = Header(default=None, alias="Authorization"),
    platform_db: Session = Depends(get_platform_db),
):
    return _sync_local_connector_customer_avatars("tiktok", payload, authorization, platform_db)


@router.post("/channels/facebook/profiles")
def sync_meta_facebook_customer_avatars(
    payload: dict,
    authorization: str | None = Header(default=None, alias="Authorization"),
    platform_db: Session = Depends(get_platform_db),
):
    return _sync_local_connector_customer_avatars(
        "facebook", payload, authorization, platform_db, replace_existing=True
    )


@router.post("/channels/instagram/profiles")
def sync_meta_instagram_customer_avatars(
    payload: dict,
    authorization: str | None = Header(default=None, alias="Authorization"),
    platform_db: Session = Depends(get_platform_db),
):
    return _sync_local_connector_customer_avatars(
        "instagram", payload, authorization, platform_db, replace_existing=True
    )


def _sync_local_connector_customer_avatars(
    channel_type: str,
    payload: dict,
    authorization: str | None,
    platform_db: Session,
    *,
    replace_existing: bool = False,
):
    """Sync avatar URLs for known connector identities; never create customers."""
    profiles = payload.get("profiles")
    if not isinstance(profiles, list) or len(profiles) > 200:
        raise HTTPException(status_code=422, detail="Danh sách hồ sơ connector không hợp lệ.")
    avatars = {}
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        external_user_id = str(profile.get("externalUserId") or "").strip()[:255]
        avatar_url = normalize_avatar_url(profile.get("avatarUrl"))
        if external_user_id and avatar_url:
            avatars[external_user_id] = avatar_url
    if not avatars:
        return {"status": "unchanged", "updated": 0}

    business_id, channel_id = _connector_channel(channel_type, authorization, platform_db)
    schema = _tenant_schema(platform_db, business_id)
    updated = 0
    matched_external_user_ids: set[str] = set()
    with tenant_session(schema) as tenant_db:
        channel = tenant_db.get(Channel, channel_id)
        if channel is None:
            raise HTTPException(status_code=401, detail="Connector không còn hợp lệ.")
        identities = tenant_db.scalars(
            select(CustomerIdentity).where(
                CustomerIdentity.business_id == business_id,
                CustomerIdentity.channel == channel_type,
                CustomerIdentity.external_account_id == str(channel.external_account_id or ""),
                CustomerIdentity.external_user_id.in_(avatars),
            )
        ).all()
        for identity in identities:
            matched_external_user_ids.add(identity.external_user_id)
            customer = identity.customer
            avatar_url = avatars.get(identity.external_user_id)
            if customer.business_id != business_id or not avatar_url:
                continue
            if customer.avatar_url == avatar_url or (customer.avatar_url and not replace_existing):
                continue
            customer.avatar_url = avatar_url
            record_audit(
                tenant_db,
                business_id=business_id,
                action="profile_update",
                resource_type="customer",
                resource_id=customer.id,
                actor_type="system",
                metadata={"fields": ["avatar_url"], "source": f"{channel_type}_connector"},
            )
            updated += 1
        tenant_db.commit()
    return {
        "status": "synced",
        "updated": updated,
        "matchedExternalUserIds": sorted(matched_external_user_ids),
    }


def _connector_exe_path(channel_type: str) -> Path | None:
    artifacts = {
        "tiktok": ("tiktok-bridge", "SmartMerchantTikTok.exe"),
        "shopee": ("shopee-bridge", "SmartMerchantShopee.exe"),
        "facebook": ("meta-business-suite-bridge", "SmartMerchantMessenger.exe"),
        "instagram": ("meta-business-suite-bridge", "SmartMerchantInstagram.exe"),
    }
    folder, filename = artifacts.get(channel_type, ("", ""))
    if not filename:
        return None
    if settings.SERVER_CONNECTOR_AGENT_URL and settings.SERVER_CONNECTOR_AGENT_TOKEN:
        folder = f"{folder}-server"
    candidates = (
        Path(__file__).resolve().parents[3] / "scripts" / "dist" / folder / filename,
        Path("/app/root-scripts/dist") / folder / filename,
        Path("/app/scripts/dist") / folder / filename,
    )
    return next((path for path in candidates if path.is_file()), None)


def _validated_connector_exe(channel_type: str) -> tuple[Path, str]:
    if channel_type not in _CHAT_SUPPORTED:
        raise HTTPException(status_code=404, detail="Kênh connector không được hỗ trợ.")
    app_path = _connector_exe_path(channel_type)
    if app_path is None:
        raise HTTPException(status_code=503, detail="Chưa có ứng dụng connector cho kênh này. Hãy báo quản trị viên.")
    try:
        if app_path.stat().st_size <= 1024 * 1024:
            raise HTTPException(status_code=503, detail="Ứng dụng connector trên máy chủ không hợp lệ.")
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Không thể đọc ứng dụng connector trên máy chủ.") from exc
    app_name = {
        "tiktok": "TikTok",
        "shopee": "Shopee",
        "facebook": "Messenger",
        "instagram": "Instagram",
    }[channel_type]
    return app_path, app_name


@router.get("/channels/{channel_type}/connector-app", dependencies=[Depends(require_admin_access)])
def download_local_connector_app(channel_type: str):
    return _connector_app_response(channel_type)


def _connector_app_response(channel_type: str, *, include_download_header: bool = True):
    app_path, app_name = _validated_connector_exe(channel_type)
    filename = f"SmartMerchant{app_name}.exe"
    server_mode = bool(settings.SERVER_CONNECTOR_AGENT_URL and settings.SERVER_CONNECTOR_AGENT_TOKEN)
    archive = BytesIO()
    with ZipFile(archive, "w", compression=ZIP_STORED) as bundle:
        bundle.write(app_path, filename)
        bundle.writestr(
            "HUONG-DAN.txt",
            (
                f"Giải nén ZIP rồi chạy {filename}. Tạo mã đúng kênh trong CRM và nhập vào ứng dụng. Ứng dụng "
                "chỉ ghép shop; Edge và worker chạy trên Windows server. Cửa sổ đăng nhập từ xa sẽ mở để bạn tự "
                "đăng nhập/xử lý CAPTCHA. Sau khi đăng nhập có thể đóng ứng dụng và máy khách; phiên tiếp tục chạy "
                "trên server.\n"
                if server_mode else (
                    f"Giải nén ZIP rồi chạy {filename}. File này chỉ ghép nối {app_name}; tạo mã đúng kênh trong CRM, "
                    f"sau đó đăng nhập thủ công trong Edge riêng của {app_name}. Connector đọc giao diện Meta Business Suite "
                    "và nhập tin nhắn vào CRM; không gọi Meta API. Connector chỉ nhập lịch sử lần đầu hoặc phần còn thiếu "
                    "khi mở lại; sau khi lịch sử hoàn tất sẽ chỉ đồng bộ tin mới. Việc mở chat có thể đánh dấu tin chưa đọc "
                    "thành đã đọc. Không vượt CAPTCHA; xử lý xác minh thủ công. Hồ sơ Edge lưu riêng trên máy này.\n"
                    if channel_type in {"facebook", "instagram"} else
                    f"Giải nén ZIP, sau đó chạy {filename}. Đăng nhập thủ công trong Edge. "
                    "Bridge đồng bộ tin nhắn và đơn đang hiển thị từ Seller Center/Kênh Người Bán về CRM; "
                    "đơn được nhập ở trạng thái nháp để kiểm tra. Giữ Edge và bridge hoạt động; "
                    "nếu nền tảng yêu cầu CAPTCHA/xác minh thì xử lý thủ công trong Edge. "
                    "Cookie và hồ sơ Edge không được gửi lên CRM.\n"
                )
            ),
        )
    headers = {"Cache-Control": "no-store"}
    if include_download_header:
        headers["Content-Disposition"] = f'attachment; filename="SmartMerchant{app_name}.zip"'
    return Response(archive.getvalue(), media_type="application/zip", headers=headers)


@router.post("/channels/{channel_type}/connector-app/download-ticket", dependencies=[Depends(require_admin_access)])
def create_connector_app_download_ticket(channel_type: str):
    _validated_connector_exe(channel_type)
    ticket = encrypt_token(
        json.dumps(
            {"purpose": "connector_app", "channel_type": channel_type, "expires_at": int(time.time()) + 300},
            separators=(",", ":"),
        ),
        settings.CHANNEL_ENCRYPTION_KEY,
    )
    return {"ticket": ticket}


@router.get("/channels/{channel_type}/connector-app/file")
def download_connector_app_with_ticket(channel_type: str, ticket: str):
    try:
        payload = json.loads(decrypt_token(ticket, settings.CHANNEL_ENCRYPTION_KEY))
        valid = (
            payload.get("purpose") == "connector_app"
            and payload.get("channel_type") == channel_type
            and int(payload.get("expires_at", 0)) > int(time.time())
        )
    except Exception:
        valid = False
    if not valid:
        raise HTTPException(status_code=404, detail="Liên kết tải file không hợp lệ hoặc đã hết hạn.")
    # This ticket route is consumed through fetch() and saved as a ZIP by the
    # browser. An attachment header lets download managers hijack that fetch.
    return _connector_app_response(channel_type, include_download_header=False)


@router.get("/channels/{channel_type}/connector-bundle", include_in_schema=False, dependencies=[Depends(require_admin_access)])
def download_local_connector_bundle_legacy(channel_type: str):
    return _connector_app_response(channel_type)
