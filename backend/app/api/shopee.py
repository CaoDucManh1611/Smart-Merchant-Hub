from fastapi import APIRouter, Request

from app.services.message_service import normalize_message

router = APIRouter(prefix="/webhooks/shopee", tags=["Shopee"])


@router.post("")
async def receive_shopee_webhook(request: Request):
    payload = await request.json()

    normalized = normalize_message(
        channel="shopee",
        payload=payload,
    )

    print("SHOPEE RAW:", payload)
    print("SHOPEE NORMALIZED:", normalized.model_dump())

    return {"status": "received"}
