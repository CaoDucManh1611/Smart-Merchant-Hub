from fastapi import APIRouter

from app.api import facebook, instagram, shopee, tiktok


api_router = APIRouter(prefix="/api")


# Facebook
api_router.include_router(
    facebook.router,
    prefix="/webhooks/facebook",
    tags=["Facebook"],
)


# Instagram
api_router.include_router(
    instagram.router,
    prefix="/webhooks/instagram",
    tags=["Instagram"],
)


# Shopee
api_router.include_router(
    shopee.router,
    prefix="/webhooks/shopee",
    tags=["Shopee"],
)


# TikTok
api_router.include_router(
    tiktok.router,
    prefix="/webhooks/tiktok",
    tags=["TikTok"],
)