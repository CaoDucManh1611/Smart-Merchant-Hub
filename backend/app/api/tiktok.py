from fastapi import APIRouter, Request

from app.services.message_service import normalize_message

router = APIRouter(prefix="/webhooks/tiktok", tags=["TikTok"])


@router.post("")
async def receive_tiktok_webhook(request: Request):
    payload = await request.json()

    normalized = normalize_message(
        channel="tiktok",
        payload=payload,
    )

    print("TIKTOK RAW:", payload)
    print("TIKTOK NORMALIZED:", normalized.model_dump())

    return {"status": "received"}
