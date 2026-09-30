import hashlib
import hmac
import io
import json
import logging
import time
from pathlib import Path
from urllib.parse import quote
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.platform_session import get_platform_db
from app.database.tenant_session import tenant_session
from app.models.channel import Channel
from app.models.business import User
from app.models.platform_control import PlatformBusiness, TenantRegistry
from app.services.message_service import process_and_save_message
from app.services.message_service import normalize_message
from app.services.realtime import manager
from app.services.channel_credentials import decrypt_token, encrypt_token
from app.auth.dependencies import require_admin_access
from app.tenancy.schema import schema_name_for, validate_schema_name
from app.tenancy.webhook import verify_tiktok_webhook_signature

router = APIRouter(tags=["TikTok"])
bridge_router = APIRouter(tags=["TikTok bridge"])
logger = logging.getLogger(__name__)


def _tiktok_bot_path() -> Path | None:
    """Find the bridge script in local development and Docker runtimes."""

    candidates = (
        Path(__file__).resolve().parents[3] / "scripts" / "tiktok_bot.py",
        Path("/app/root-scripts/tiktok_bot.py"),
        Path("/app/scripts/tiktok_bot.py"),
    )
    return next((path for path in candidates if path.is_file()), None)


def _tiktok_exe_path() -> Path | None:
    """Find the built Windows bridge shipped with the backend."""

    candidates = (
        Path(__file__).resolve().parents[3] / "scripts" / "dist" / "tiktok-bridge" / "SmartMerchantTikTok.exe",
        Path("/app/root-scripts/dist/tiktok-bridge/SmartMerchantTikTok.exe"),
        Path("/app/scripts/dist/tiktok-bridge/SmartMerchantTikTok.exe"),
    )
    return next((path for path in candidates if path.is_file()), None)


@router.post("")
async def receive_tiktok_webhook(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    raw_body = await request.body()

    if not settings.TIKTOK_APP_KEY or not settings.TIKTOK_APP_SECRET:
        raise HTTPException(status_code=503, detail="TikTok webhook is not configured")
    if not verify_tiktok_webhook_signature(
        raw_body,
        authorization=authorization,
        app_key=settings.TIKTOK_APP_KEY,
        app_secret=settings.TIKTOK_APP_SECRET,
    ):
        raise HTTPException(status_code=401, detail="Invalid TikTok webhook signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid TikTok webhook JSON") from exc

    normalized = normalize_message(
        channel="tiktok",
        payload=payload,
    )

    # ``normalize_message`` returns a dict, and payloads must never be
    # printed because they may include customer content or provider secrets.
    logger.info(
        "TikTok webhook received: is_message=%s",
        bool(normalized.get("external_message_id")),
    )

    return {"status": "received"}


@bridge_router.get("/bot-file", dependencies=[Depends(require_admin_access)])
def download_tiktok_bot_file():
    path = _tiktok_bot_path()
    if path is None:
        raise HTTPException(status_code=404, detail="Chưa có file tiktok_bot.py trên máy chủ")
    return FileResponse(
        path,
        media_type="text/x-python",
        filename="tiktok_bot.py",
    )


@bridge_router.post("/bot-file", dependencies=[Depends(require_admin_access)])
def download_configured_tiktok_bot_file(
    payload: dict,
    platform_db: Session = Depends(get_platform_db),
    actor: User | None = Depends(require_admin_access),
):
    """Download a bridge already configured for the authenticated shop.

    The bridge secret is validated against the tenant before it is embedded in
    the one-click file. This removes copy/paste setup while keeping the secret
    out of the generic public download and out of the database in plain text.
    """

    try:
        business_id = int(payload.get("business_id"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Thiếu shop cần cấu hình TikTok") from exc

    if actor is not None and int(actor.business_id or 0) != business_id:
        raise HTTPException(status_code=404, detail="Shop TikTok không tồn tại")

    business = platform_db.scalar(
        select(PlatformBusiness).where(
            PlatformBusiness.id == business_id,
            PlatformBusiness.status == "active",
        )
    )
    if business is None:
        raise HTTPException(status_code=404, detail="Shop TikTok không tồn tại")

    shop_slug = str(payload.get("shop_slug") or "").strip().lower()
    expected_slug = str(business.slug or "").strip().lower()
    bridge_secret = str(payload.get("bridge_secret") or "").strip()
    if not shop_slug or shop_slug != expected_slug or len(bridge_secret) < 32:
        raise HTTPException(status_code=401, detail="Thông tin cấu hình TikTok không hợp lệ")

    with tenant_session(schema_name_for(business_id)) as db:
        channel = db.scalar(
            select(Channel).where(
                Channel.business_id == business_id,
                Channel.channel_type == "tiktok",
                Channel.external_account_id == f"tiktok-bridge-{business_id}",
                Channel.status == "active",
            )
        )
        if channel is None:
            raise HTTPException(status_code=404, detail="Shop chưa bật TikTok bridge")
        config = channel.config if isinstance(channel.config, dict) else {}
        expected_secret = str(config.get("webhook_secret") or "").strip()
        encrypted_secret = config.get("webhook_secret_encrypted")
        if encrypted_secret:
            try:
                expected_secret = decrypt_token(str(encrypted_secret), settings.CHANNEL_ENCRYPTION_KEY)
            except (LookupError, TypeError, ValueError):
                expected_secret = ""
        if not expected_secret or not hmac.compare_digest(expected_secret, bridge_secret):
            raise HTTPException(status_code=401, detail="Mã bảo vệ TikTok bridge không đúng")

    backend_url = str(payload.get("backend_url") or "").strip().rstrip("/")
    if not backend_url.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="Địa chỉ máy chủ TikTok không hợp lệ")

    if str(payload.get("format") or "").strip().lower() == "exe" and payload.get("delivery") == "url":
        download_payload = json.dumps(
            {
                "business_id": business_id,
                "shop_slug": shop_slug,
                "bridge_secret": bridge_secret,
                "backend_url": backend_url,
                "format": "exe",
                "expires_at": int(time.time()) + 900,
            },
            separators=(",", ":"),
        )
        token = encrypt_token(download_payload, settings.CHANNEL_ENCRYPTION_KEY)
        return {
            "download_url": f"/api/channels/tiktok/bot-file/download?token={quote(token, safe='')}"
        }

    path = _tiktok_bot_path()
    if path is None:
        raise HTTPException(status_code=404, detail="Chưa có file tiktok_bot.py trên máy chủ")

    source = path.read_text(encoding="utf-8")
    # Keep the generated bridge compatible with both the current frozen-aware
    # launcher and older source bundles that used a plain ``__file__`` base.
    marker = next(
        (
            candidate
            for candidate in (
                "BASE=Path(sys.executable).resolve().parent if IS_FROZEN else Path(__file__).resolve().parent\n",
                "BASE=Path(__file__).resolve().parent\n",
            )
            if candidate in source
        ),
        None,
    )
    defaults = {
        "TIKTOK_BACKEND_URL": backend_url,
        "TIKTOK_SHOP_SLUG": shop_slug,
        "TIKTOK_BRIDGE_SECRET": bridge_secret,
    }
    embedded = (
        "\n# Smart Merchant defaults: generated for one shop.\n"
        "# Override with environment variables when troubleshooting.\n"
        f"_EMBEDDED_CONFIG = {json.dumps(defaults, ensure_ascii=False)}\n"
        "for _key, _value in _EMBEDDED_CONFIG.items():\n"
        "    os.environ.setdefault(_key, _value)\n"
    )
    if marker is None:
        raise HTTPException(status_code=500, detail="File TikTok bridge không đúng phiên bản")
    configured_source = source.replace(marker, marker + embedded, 1)
    if str(payload.get("format") or "").strip().lower() == "exe":
        exe_path = _tiktok_exe_path()
        if exe_path is None:
            raise HTTPException(status_code=404, detail="Chưa có bản SmartMerchantTikTok.exe trên máy chủ")
        try:
            if exe_path.stat().st_size <= 0:
                raise HTTPException(status_code=503, detail="Bản SmartMerchantTikTok.exe trên máy chủ đang rỗng")
        except OSError as exc:
            raise HTTPException(status_code=503, detail="Không thể đọc bản SmartMerchantTikTok.exe trên máy chủ") from exc
        archive = io.BytesIO()
        with ZipFile(archive, "w", compression=ZIP_DEFLATED) as package:
            package.write(exe_path, "SmartMerchantTikTok.exe")
            package.writestr(
                "tiktok_config.json",
                json.dumps(
                    {
                        "TIKTOK_BACKEND_URL": backend_url,
                        "TIKTOK_SHOP_SLUG": shop_slug,
                        "TIKTOK_BRIDGE_SECRET": bridge_secret,
                    },
                    ensure_ascii=False,
                    indent=2,
                ) + "\n",
            )
            package.writestr(
                "README.txt",
                "Giai nen cung thu muc, sau do mo SmartMerchantTikTok.exe.\n"
                "Ung dung tu doc phien TikTok tren may nay va tu dong gui tin ve CRM.\n"
                "Khong gui file tiktok_config.json cho nguoi khac.\n",
            )
        archive_bytes = archive.getvalue()
        if not archive_bytes:
            raise HTTPException(status_code=503, detail="Không thể tạo file ZIP TikTok")
        return Response(
            content=archive_bytes,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="SmartMerchantTikTok.zip"',
                "Cache-Control": "no-store",
            },
        )
    return Response(
        content=configured_source.encode("utf-8"),
        media_type="text/x-python; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="tiktok_bot.py"'},
    )


@bridge_router.get("/bot-file/download")
def download_configured_tiktok_bot_file_by_token(
    token: str,
    platform_db: Session = Depends(get_platform_db),
):
    """Serve a short-lived native download URL for browsers that truncate Blob downloads."""

    try:
        raw_payload = decrypt_token(token, settings.CHANNEL_ENCRYPTION_KEY)
        payload = json.loads(raw_payload)
        if int(payload.get("expires_at", 0)) <= int(time.time()):
            raise ValueError("expired")
        payload.pop("expires_at", None)
        payload.pop("delivery", None)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Liên kết tải file TikTok không hợp lệ hoặc đã hết hạn") from exc

    return download_configured_tiktok_bot_file(payload, platform_db=platform_db, actor=None)


def _bridge_message_id(payload: dict) -> str:
    """Use the provider id when available, otherwise make a stable id."""

    value = str(payload.get("messageId") or payload.get("msg_id") or "").strip()
    if value:
        return value
    seed = "|".join(
        str(payload.get(key) or "").strip()
        for key in ("threadId", "authorId", "message", "aweType")
    )
    return "bridge-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


@bridge_router.post("/incoming")
async def receive_tiktok_bridge_message(
    payload: dict,
    platform_db: Session = Depends(get_platform_db),
    x_tiktok_shop_slug: str | None = Header(default=None, alias="X-TikTok-Shop-Slug"),
    x_tiktok_bridge_secret: str | None = Header(default=None, alias="X-TikTok-Bridge-Secret"),
):
    """Accept messages from the local ReLttk bridge for one shop only.

    The bridge runs on the shop's machine, so it cannot use TikTok's signed
    Shop API webhook format.  A per-shop secret and slug still keep the event
    tenant-scoped and prevent a bridge from writing into another shop.
    """

    slug = str(x_tiktok_shop_slug or "").strip().lower()
    provided_secret = str(x_tiktok_bridge_secret or "").strip()
    if not slug or not provided_secret:
        raise HTTPException(status_code=401, detail="Thiếu mã bảo vệ TikTok bridge")

    business = platform_db.scalar(
        select(PlatformBusiness).where(
            PlatformBusiness.slug == slug,
            PlatformBusiness.status == "active",
        )
    )
    if business is None:
        raise HTTPException(status_code=404, detail="Shop TikTok không tồn tại")

    registry = platform_db.scalar(
        select(TenantRegistry).where(TenantRegistry.business_id == int(business.id))
    )
    if registry is not None and registry.state not in {"active", "ready"}:
        raise HTTPException(status_code=423, detail="Shop đang được chuẩn bị")
    schema_name = validate_schema_name(
        str(registry.schema_name) if registry is not None else schema_name_for(int(business.id))
    )

    with tenant_session(schema_name) as db:
        channel = db.scalar(
            select(Channel).where(
                Channel.business_id == int(business.id),
                Channel.channel_type == "tiktok",
                Channel.external_account_id == f"tiktok-bridge-{int(business.id)}",
                Channel.status == "active",
            )
        )
        if channel is None:
            raise HTTPException(status_code=404, detail="Shop chưa bật TikTok bridge")

        config = channel.config if isinstance(channel.config, dict) else {}
        expected_secret = str(config.get("webhook_secret") or "").strip()
        encrypted_secret = config.get("webhook_secret_encrypted")
        if encrypted_secret:
            try:
                expected_secret = decrypt_token(str(encrypted_secret), settings.CHANNEL_ENCRYPTION_KEY)
            except (LookupError, TypeError, ValueError):
                expected_secret = ""
        if not expected_secret or not hmac.compare_digest(expected_secret, provided_secret):
            raise HTTPException(status_code=401, detail="Mã bảo vệ TikTok bridge không đúng")

        sender_id = str(payload.get("authorId") or payload.get("sender_id") or "").strip()
        if not sender_id:
            raise HTTPException(status_code=422, detail="Thiếu người gửi TikTok")
        content = str(payload.get("message") or payload.get("text") or "").strip()
        allowed_media_types = {"image", "video", "audio", "file", "sticker"}
        media_type = str(payload.get("mediaType") or payload.get("media_type") or "").strip().lower()
        if media_type not in allowed_media_types:
            media_type = ""
        media_url = str(payload.get("mediaUrl") or payload.get("media_url") or "").strip() or None
        attachments = payload.get("attachments")
        if not isinstance(attachments, list):
            attachments = []
        if media_type and not attachments:
            attachments = [{
                "media_type": media_type,
                "url": media_url,
                "external_attachment_id": str(payload.get("mediaId") or "").strip() or None,
                "metadata": {"awe_type": payload.get("aweType")},
            }]
        saved = process_and_save_message(
            db=db,
            message={
                "channel": "tiktok",
                "external_account_id": channel.external_account_id,
                "external_user_id": sender_id,
                "external_message_id": _bridge_message_id(payload),
                "content": content,
                "name": payload.get("displayName"),
                "display_name": payload.get("displayName"),
                "username": payload.get("username"),
                "avatar_url": payload.get("avatarUrl") or payload.get("avatar_url"),
                "media_type": media_type or None,
                "media_url": media_url,
                "attachments": attachments,
                "raw_payload": payload,
                "business_id": int(business.id),
                "channel_id": channel.id,
            },
        )
        if not isinstance(saved, dict):
            raise HTTPException(status_code=500, detail="Không thể lưu tin nhắn TikTok")
        if saved.get("_created", True):
            await manager.broadcast(
                {
                    "type": "message_created",
                    "conversation_id": saved.get("conversation_id"),
                    "message": {key: value for key, value in saved.items() if key != "_created"},
                },
                business_id=int(business.id),
            )
        return {"status": "received", "processed": 1 if saved.get("_created", True) else 0}
