"""
test_webhook_simulate.py
========================
Simulate Meta gui webhook event den FastAPI server dang chay local.
Dung de test nhanh ma KHONG can ngrok hay Meta Dashboard.

Cach chay:
    1. Mo terminal 1 -> chay server:
       uvicorn app.main:app --reload --port 8000

    2. Mo terminal 2 -> chay script nay:
       python test_webhook_simulate.py

Xem ket qua o terminal 1 (server log).
"""

import sys
import httpx
import json
import time

# Fix Unicode print tren Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_URL = "http://localhost:8000"
INSTAGRAM_WEBHOOK_URL = f"{BASE_URL}/api/webhooks/instagram"
VERIFY_TOKEN = "crm_chatbot_2026"


# ─────────────────────────────────────────────
# Payload mẫu — giống hệt Meta gửi thật
# ─────────────────────────────────────────────

def make_dm_payload(
    sender_id: str = "USER_PSID_12345",
    recipient_id: str = "PAGE_PSID_67890",
    message_text: str = "Xin chào, tôi muốn hỏi về sản phẩm!",
    mid: str = "mid.test.abc123",
) -> dict:
    """Tạo payload DM giống Meta gửi thật."""
    return {
        "object": "instagram",
        "entry": [
            {
                "id": recipient_id,
                "time": int(time.time() * 1000),
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "recipient": {"id": recipient_id},
                        "timestamp": int(time.time() * 1000),
                        "message": {
                            "mid": mid,
                            "text": message_text,
                        },
                    }
                ],
            }
        ],
    }


def make_story_reply_payload(
    sender_id: str = "USER_PSID_12345",
    recipient_id: str = "PAGE_PSID_67890",
) -> dict:
    """Payload story reply — không có text, dùng để test edge case."""
    return {
        "object": "instagram",
        "entry": [
            {
                "id": recipient_id,
                "time": int(time.time() * 1000),
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "recipient": {"id": recipient_id},
                        "timestamp": int(time.time() * 1000),
                        "message": {
                            "mid": "mid.story.xyz",
                            # Không có "text" — story mention/reply
                            "attachments": [
                                {
                                    "type": "story_mention",
                                    "payload": {"url": "https://..."},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def make_empty_entry_payload() -> dict:
    """Payload rỗng — test trường hợp entry không có messaging."""
    return {
        "object": "instagram",
        "entry": [{"id": "123", "time": int(time.time() * 1000)}],
    }


# ─────────────────────────────────────────────
# Test functions
# ─────────────────────────────────────────────

def print_divider(title: str):
    print(f"\n{'=' * 55}")
    print(f"  {title}")
    print("=" * 55)


def test_verify_webhook():
    """Test GET /api/webhooks/instagram — giả lập Meta verify."""
    print_divider("TEST 1: Verify Webhook (GET)")

    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": VERIFY_TOKEN,
        "hub.challenge": "CHALLENGE_RESPONSE_12345",
    }

    resp = httpx.get(INSTAGRAM_WEBHOOK_URL, params=params)

    print(f"Status : {resp.status_code}")
    print(f"Body   : {resp.text!r}")

    if resp.status_code == 200 and resp.text == "CHALLENGE_RESPONSE_12345":
        print("✅ Verification PASSED")
    else:
        print("❌ Verification FAILED")


def test_verify_wrong_token():
    """Test GET với sai verify_token — phải trả 403."""
    print_divider("TEST 2: Verify với sai token (phải 403)")

    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "WRONG_TOKEN",
        "hub.challenge": "abc",
    }

    resp = httpx.get(INSTAGRAM_WEBHOOK_URL, params=params)

    print(f"Status : {resp.status_code}")
    if resp.status_code == 403:
        print("✅ Đúng — trả 403 khi sai token")
    else:
        print(f"❌ Sai — expected 403, got {resp.status_code}")


def test_receive_dm():
    """Test POST — gửi DM payload thật."""
    print_divider("TEST 3: Nhận DM thật (POST)")

    payload = make_dm_payload(
        message_text="Xin chào! Cho tôi hỏi giá sản phẩm A?"
    )

    print("Payload gửi đi:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    resp = httpx.post(INSTAGRAM_WEBHOOK_URL, json=payload)

    print(f"\nStatus : {resp.status_code}")
    print(f"Body   : {resp.json()}")

    if resp.status_code == 200 and resp.json().get("status") == "received":
        print("✅ POST nhận DM PASSED")
    else:
        print("❌ POST nhận DM FAILED")


def test_receive_story_reply():
    """Test POST — story reply không có text."""
    print_divider("TEST 4: Story reply không có text (POST)")

    payload = make_story_reply_payload()
    resp = httpx.post(INSTAGRAM_WEBHOOK_URL, json=payload)

    print(f"Status : {resp.status_code}")
    print(f"Body   : {resp.json()}")

    if resp.status_code == 200:
        print("✅ Story reply PASSED (server không crash)")
    else:
        print("❌ Story reply FAILED")


def test_receive_empty_entry():
    """Test POST — entry rỗng không có messaging."""
    print_divider("TEST 5: Entry rỗng (POST)")

    payload = make_empty_entry_payload()
    resp = httpx.post(INSTAGRAM_WEBHOOK_URL, json=payload)

    print(f"Status : {resp.status_code}")
    print(f"Body   : {resp.json()}")

    if resp.status_code == 200:
        print("✅ Empty entry PASSED (server không crash)")
    else:
        print("❌ Empty entry FAILED")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("\n[START] Instagram Webhook Simulator")
    print(f"   Target: {INSTAGRAM_WEBHOOK_URL}")

    # Kiem tra server co dang chay khong
    try:
        health = httpx.get(f"{BASE_URL}/health", timeout=3)
        print(f"   Server: [OK] dang chay (status={health.status_code})")
    except httpx.ConnectError:
        print(
            "\n[FAIL] Khong ket noi duoc server!\n"
            "   -> Hay chay truoc: uvicorn app.main:app --reload --port 8000\n"
        )
        raise SystemExit(1)

    test_verify_webhook()
    test_verify_wrong_token()
    test_receive_dm()
    test_receive_story_reply()
    test_receive_empty_entry()

    print("\n" + "=" * 55)
    print("  Xong! Kiem tra terminal server de xem log.")
    print("=" * 55 + "\n")
