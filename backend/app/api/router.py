from fastapi import APIRouter

from app.api import facebook, instagram, shopee, tiktok

api_router = APIRouter(prefix="/api")

api_router.include_router(facebook.router)
api_router.include_router(instagram.router)
api_router.include_router(shopee.router)
api_router.include_router(tiktok.router)
