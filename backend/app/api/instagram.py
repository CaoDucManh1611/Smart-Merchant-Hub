from fastapi import APIRouter, Request

from app.services.message_service import normalize_message

router = APIRouter(prefix="/webhooks/instagram", tags=["Instagram"])


@router.post("")
async def receive_instagram_webhook(request: Request):
    payload = await request.json()

    normalized = normalize_message(
        channel="instagram",
        payload=payload,
    )

    print("INSTAGRAM RAW:", payload)
    print("INSTAGRAM NORMALIZED:", normalized.model_dump())

    return {"status": "received"}
