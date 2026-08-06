from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
)

app.include_router(api_router)


@app.get("/")
async def root():
    return {
        "message": "CRM Chatbot API is running",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    return {"status": "ok"}
