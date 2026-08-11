"""
tests/test_instagram_webhook.py
================================
Pytest tests cho endpoint Instagram Webhook.
Chạy: pytest tests/ -v
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

VERIFY_TOKEN = "crm_chatbot_2026"
WEBHOOK_URL = "/api/webhooks/instagram"


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def dm_payload(
    text: str = "Xin chào",
    sender_id: str = "USER_111",
    recipient_id: str = "PAGE_222",
    mid: str = "mid.test.001",
) -> dict:
    return {
        "object": "instagram",
        "entry": [
            {
                "id": recipient_id,
                "time": 1_700_000_000_000,
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "recipient": {"id": recipient_id},
                        "timestamp": 1_700_000_000_000,
                        "message": {"mid": mid, "text": text},
                    }
                ],
            }
        ],
    }


# ─────────────────────────────────────────────
# GET — Verify webhook
# ─────────────────────────────────────────────

class TestVerifyWebhook:
    def test_verify_success(self):
        """Meta gửi đúng token → trả lại hub.challenge."""
        resp = client.get(
            WEBHOOK_URL,
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "MY_CHALLENGE_123",
            },
        )
        assert resp.status_code == 200
        assert resp.text == "MY_CHALLENGE_123"

    def test_verify_wrong_token(self):
        """Sai token → 403."""
        resp = client.get(
            WEBHOOK_URL,
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "WRONG_TOKEN",
                "hub.challenge": "abc",
            },
        )
        assert resp.status_code == 403

    def test_verify_wrong_mode(self):
        """Mode không phải subscribe → 403."""
        resp = client.get(
            WEBHOOK_URL,
            params={
                "hub.mode": "unsubscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "abc",
            },
        )
        assert resp.status_code == 403


# ─────────────────────────────────────────────
# POST — Nhận webhook event
# ─────────────────────────────────────────────

class TestReceiveWebhook:
    def test_receive_dm_returns_200(self):
        """POST với DM payload hợp lệ → 200."""
        resp = client.post(WEBHOOK_URL, json=dm_payload())
        assert resp.status_code == 200
        assert resp.json()["status"] == "received"

    def test_receive_dm_message_text(self):
        """Server nhận đúng nội dung text."""
        # Chỉ kiểm tra server không crash và trả 200
        resp = client.post(
            WEBHOOK_URL,
            json=dm_payload(text="Cho hỏi giá sản phẩm?"),
        )
        assert resp.status_code == 200

    def test_receive_empty_entry(self):
        """Entry rỗng (không có messaging) → 200, không crash."""
        payload = {
            "object": "instagram",
            "entry": [{"id": "123", "time": 123456789}],
        }
        resp = client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200

    def test_receive_no_entry(self):
        """Không có entry → 200, không crash."""
        payload = {"object": "instagram", "entry": []}
        resp = client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200

    def test_receive_no_message_field(self):
        """Messaging event không có 'message' (vd: seen, reaction) → 200."""
        payload = {
            "object": "instagram",
            "entry": [
                {
                    "id": "PAGE_222",
                    "time": 123456,
                    "messaging": [
                        {
                            "sender": {"id": "USER_111"},
                            "recipient": {"id": "PAGE_222"},
                            "timestamp": 123456,
                            "read": {"watermark": 123456},  # "seen" event
                        }
                    ],
                }
            ],
        }
        resp = client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200

    def test_receive_story_mention(self):
        """Story mention (attachment, không có text) → 200."""
        payload = {
            "object": "instagram",
            "entry": [
                {
                    "id": "PAGE_222",
                    "time": 123456,
                    "messaging": [
                        {
                            "sender": {"id": "USER_111"},
                            "recipient": {"id": "PAGE_222"},
                            "timestamp": 123456,
                            "message": {
                                "mid": "mid.story.001",
                                "attachments": [
                                    {
                                        "type": "story_mention",
                                        "payload": {"url": "https://example.com"},
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
        resp = client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200


# ─────────────────────────────────────────────
# Message normalization
# ─────────────────────────────────────────────

class TestMessageNormalization:

    def test_normalize_instagram_dm(self):
        """normalize_message trả đúng fields cho Instagram DM."""

        from app.services.message_service import normalize_message

        payload = dm_payload(
            text="Hello shop!",
            sender_id="USER_AAA",
            mid="mid.normalize.001",
        )

        result = normalize_message(
            channel="instagram",
            payload=payload,
        )

        assert result["channel"] == "instagram"
        assert result["external_user_id"] == "USER_AAA"
        assert result["external_message_id"] == "mid.normalize.001"
        assert result["content"] == "Hello shop!"


    def test_normalize_empty_entry(self):
        """Entry rỗng → trả empty_normalized_message."""

        from app.services.message_service import normalize_message

        payload = {
            "object": "instagram",
            "entry": [],
        }

        result = normalize_message(
            channel="instagram",
            payload=payload,
        )

        assert result["channel"] == "instagram"
        assert result["external_user_id"] is None
        assert result["content"] is None
