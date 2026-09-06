from fastapi import APIRouter
from app.api import auth, conversations, documents, chat, meta_oauth, customers, sales, purchase_orders, suppliers, inventory, payments, leads, tickets, team, workflows, reports, notifications, experimentation, media
from app.api import facebook, instagram, shopee, tiktok, telegram, zalo


api_router = APIRouter(prefix="/api")

api_router.include_router(auth.router, tags=["Auth"])

api_router.include_router(
    meta_oauth.router,
    prefix="/oauth",
    tags=["Meta OAuth"],
)


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

api_router.include_router(
    telegram.router,
    prefix="/webhooks/telegram",
    tags=["Telegram"],
)


# Zalo Bot Creator
api_router.include_router(
    zalo.router,
    prefix="/webhooks/zalo",
    tags=["Zalo"],
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

api_router.include_router(
    conversations.router,
    prefix="/conversations",
    tags=["Conversations"],
)


# RAG – Document Management
api_router.include_router(
    documents.router,
    prefix="/documents",
    tags=["Documents"],
)


# RAG – Chat
api_router.include_router(
    chat.router,
    prefix="/chat",
    tags=["Chat"],
)

api_router.include_router(
    customers.router,
    prefix="/customers",
    tags=["Customers"],
)

api_router.include_router(
    sales.router,
    tags=["Sales"],
)

api_router.include_router(
    purchase_orders.router,
    tags=["Purchase Orders"],
)

api_router.include_router(
    suppliers.router,
    tags=["Suppliers"],
)

api_router.include_router(
    inventory.router,
    tags=["Inventory"],
)

api_router.include_router(
    payments.router,
    tags=["Payments"],
)

api_router.include_router(
    leads.router,
    tags=["Leads"],
)

api_router.include_router(
    tickets.router,
    tags=["Tickets"],
)

api_router.include_router(
    team.router,
    tags=["Team"],
)

api_router.include_router(
    workflows.router,
    tags=["Workflows"],
)

api_router.include_router(
    notifications.router,
    tags=["Notifications"],
)

api_router.include_router(
    experimentation.router,
    tags=["Experimentation"],
)

api_router.include_router(
    reports.router,
    tags=["Reports"],
)

api_router.include_router(
    media.router,
    prefix="/media",
    tags=["Media"],
)
