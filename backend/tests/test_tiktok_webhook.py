import hashlib
import hmac
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


client = TestClient(app)


def _signed_request(payload: dict, *, app_key: str = "tiktok-app-key", secret: str = "tiktok-app-secret"):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(
        secret.encode("utf-8"),
        app_key.encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()
    return body, {"Authorization": signature}


def test_tiktok_webhook_accepts_valid_signature_on_public_callback_path():
    payload = {"type": 1, "shop_id": "shop-1", "data": {"order_id": "order-1"}}
    body, headers = _signed_request(payload)

    with patch.dict(
        settings.__dict__,
        {"TIKTOK_APP_KEY": "tiktok-app-key", "TIKTOK_APP_SECRET": "tiktok-app-secret"},
    ):
        response = client.post("/api/webhooks/tiktok", content=body, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"status": "received"}


def test_tiktok_webhook_rejects_missing_or_invalid_signature():
    payload = {"type": 1, "shop_id": "shop-1"}
    body, _ = _signed_request(payload)

    with patch.dict(
        settings.__dict__,
        {"TIKTOK_APP_KEY": "tiktok-app-key", "TIKTOK_APP_SECRET": "tiktok-app-secret"},
    ):
        missing = client.post("/api/webhooks/tiktok", content=body)
        invalid = client.post(
            "/api/webhooks/tiktok",
            content=body,
            headers={"Authorization": "invalid-signature"},
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401
