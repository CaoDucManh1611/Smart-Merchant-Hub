import logging
from threading import Thread

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.database.init_db import init_db
from app.services.realtime import manager
from app.services.knowledge_seed_service import seed_knowledge_base

logger = logging.getLogger(__name__)


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
)


@app.on_event("startup")
def initialize_database() -> None:
    """Ensure pgvector, tables and indexes exist before serving requests."""
    try:
        init_db()
        Thread(
            target=seed_knowledge_base,
            name="knowledge-base-seed",
            daemon=True,
        ).start()
    except Exception:
        logger.exception("Database initialization failed")
        raise


# =========================================================
# CORS
# Cho phép Vue frontend gọi FastAPI từ mọi origin
# =========================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
