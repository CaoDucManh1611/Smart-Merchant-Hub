from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.dependencies import get_db
from app.services.monapay_webhook_service import receive_transaction

router = APIRouter()


@router.post("/webhooks/monapay")
async def monapay_webhook(request: Request, db: Session = Depends(get_db)):
    content_length = request.headers.get("content-length")
    if content_length and (not content_length.isdigit() or int(content_length) > 64 * 1024):
        raise HTTPException(413, "MONA Pay webhook payload is too large")
    raw_body = bytearray()
    async for chunk in request.stream():
        raw_body.extend(chunk)
        if len(raw_body) > 64 * 1024:
            raise HTTPException(413, "MONA Pay webhook payload is too large")
    return receive_transaction(
        db,
        bytes(raw_body),
        request.headers.get("x-mona-timestamp", ""),
        request.headers.get("x-mona-signature", ""),
    )
