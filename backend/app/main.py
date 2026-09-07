import logging
from pathlib import Path
from threading import Thread

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.database.init_db import init_db
from app.middleware.security import RateLimitMiddleware, SecurityHeadersMiddleware
from app.services.realtime import manager
from app.services.knowledge_seed_service import seed_knowledge_base

logger = logging.getLogger(__name__)
configure_logging()

ZALO_VERIFICATION_DIR = Path(__file__).resolve().parent / "zalo_verification"


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
)


@app.on_event("startup")
def initialize_database() -> None:
    """Ensure pgvector, tables and indexes exist before serving requests."""
    try:
        settings.validate_runtime()
        init_db()
        Thread(
            target=seed_knowledge_base,
            name="knowledge-base-seed",
            daemon=True,
        ).start()
    except Exception:
        logger.exception("Database initialization failed")
        raise


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
)



# =========================================================
# API ROUTER
# =========================================================

app.include_router(api_router)


@app.websocket("/ws/conversations")
async def conversations_websocket(
    websocket: WebSocket,
):
    await manager.connect(
        websocket
    )

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(
            websocket
        )


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
