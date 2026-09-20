import logging
from contextlib import asynccontextmanager
from pathlib import Path

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.database.init_db import init_db
from app.database.release_readiness import assert_release_database_ready
from app.database.platform_session import PlatformSessionLocal
from app.database.session import SessionLocal
from app.auth.dependencies import decode_token_payload, token_hash
from app.models.auth_session import AuthSession
from app.models.business import User
from app.middleware.security import RateLimitMiddleware, SecurityHeadersMiddleware
from app.services.realtime import manager
from app.services.observability import (
    collect_operational_snapshot,
    evaluate_alerts,
    observed_at,
    prometheus_text,
)

logger = logging.getLogger(__name__)
configure_logging()

ZALO_VERIFICATION_DIR = Path(__file__).resolve().parent / "zalo_verification"


def initialize_database() -> None:
    """Validate production migrations; mutate schemas only in local legacy mode."""
    try:
        settings.validate_runtime()
        if settings.ENVIRONMENT.strip().lower() == "production":
            assert_release_database_ready()
        else:
            init_db()
    except Exception:
        logger.exception("Database initialization failed")
        raise


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["http://localhost:5173"],
    allow_credentials=bool(settings.cors_origins and "*" not in settings.cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
)

if "*" not in settings.allowed_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

if settings.FORCE_HTTPS:
    app.add_middleware(HTTPSRedirectMiddleware)

app.add_middleware(
    SecurityHeadersMiddleware,
    hsts_enabled=settings.HSTS_ENABLED,
)
app.add_middleware(
    RateLimitMiddleware,
    enabled=settings.RATE_LIMIT_ENABLED,
    max_requests=settings.RATE_LIMIT_REQUESTS,
    window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
    trusted_proxy=settings.RATE_LIMIT_TRUSTED_PROXY,
    backend=settings.RATE_LIMIT_BACKEND,
    redis_url=settings.REDIS_URL,
)



# =========================================================
# API ROUTER
# =========================================================

app.include_router(api_router)


@app.websocket("/ws/conversations")
async def conversations_websocket(
    websocket: WebSocket,
):
    """Open a realtime channel bound to one authenticated shop member.

    Browser WebSockets cannot attach the normal Authorization header, so the
    existing bearer session is supplied as a query parameter over the same
    protected origin.  The token is verified against the durable session row
    before the socket is accepted; events can then be scoped by business.
    """
    token = (websocket.query_params.get("access_token") or "").strip()
    try:
        claims = decode_token_payload(token)
        # Login sessions and CRM users still live in the operational CRM
        # database. The platform control plane intentionally has a separate
        # schema, so validating this socket there rejects otherwise valid
        # shop sessions and makes staff presence unavailable.
        with SessionLocal() as db:
            session = db.query(AuthSession).filter(
                AuthSession.token_hash == token_hash(token),
                AuthSession.revoked_at.is_(None),
            ).first()
            user = db.query(User).filter(
                User.id == (session.user_id if session else None),
                User.is_active.is_(True),
            ).first()
            valid_claims = (
                session is not None
                and user is not None
                and user.business_id is not None
                and session.expires_at > datetime.now(timezone.utc).replace(tzinfo=None)
                and int(claims.get("sub", 0)) == session.user_id
                and int(claims.get("business_id", 0)) == user.business_id
                and not (user.mfa_status == "enabled" and not session.mfa_verified)
            )
            if not valid_claims:
                raise ValueError("invalid realtime session")
            business_id, user_id = int(user.business_id), int(user.id)
    except (HTTPException, TypeError, ValueError):
        await websocket.close(code=4401)
        return

    await manager.connect(websocket, business_id=business_id, user_id=user_id)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        # Presence must be released for every terminal socket path, not only
        # the normal browser-close exception. Otherwise an absent assignee
        # could keep receiving private-only notifications until a restart.
        manager.disconnect(websocket)


# =========================================================
# ROOT
# =========================================================

@app.get("/")
async def root():
    return {
        "message": "CRM Chatbot API is running",
        "docs": "/docs",
    }


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/health")
async def health_check():
    return {
        "status": "ok"
    }


@app.get("/health/details")
def health_details():
    """Expose safe component readiness counters for operators and probes.

    The legacy ``/health`` contract stays intentionally minimal for load
    balancers.  This diagnostic endpoint checks the database-backed queue and
    reports provider circuit state without exposing exception text or secrets.
    """
    with PlatformSessionLocal() as db:
        checks = collect_operational_snapshot(db)
    alerts = evaluate_alerts(checks)
    overall = "ok" if all(item["status"] in {"ok", "disabled"} for item in checks.values()) else "degraded"
    return {"status": overall, "checks": checks, "alerts": alerts, "observed_at": observed_at()}


@app.get("/health/alerts")
def health_alerts():
    """Return threshold alerts for Prometheus/Alertmanager polling."""
    with PlatformSessionLocal() as db:
        snapshot = collect_operational_snapshot(db)
    return {"alerts": evaluate_alerts(snapshot), "observed_at": observed_at()}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    """Prometheus-safe counters and gauges for database/queue/AI cost."""
    with PlatformSessionLocal() as db:
        snapshot = collect_operational_snapshot(db)
    return PlainTextResponse(prometheus_text(snapshot), media_type="text/plain; version=0.0.4")


@app.get("/{filename:path}", include_in_schema=False)
async def zalo_domain_verification_file(filename: str):
    """Serve only Zalo's downloaded domain-verification HTML files."""
    if (
        not filename.lower().startswith("zalo_verifier")
        or not filename.lower().endswith(".html")
        or "/" in filename
        or "\\" in filename
    ):
        raise HTTPException(status_code=404, detail="Not Found")

    verification_dir = ZALO_VERIFICATION_DIR.resolve()
    candidate = (verification_dir / filename).resolve()
    if candidate.parent != verification_dir or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(candidate, media_type="text/html")
