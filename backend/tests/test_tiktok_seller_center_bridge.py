import sys
from pathlib import Path

import pytest


_SCRIPTS = Path(__file__).parents[2] / "scripts"
sys.path.insert(0, str(_SCRIPTS))
from tiktok_bot import (  # noqa: E402
    TikTokDeliveryUnknown,
    _is_seller_chat_url,
    _loaded_seller_history,
    _message_is_fresh,
    _open_seller_conversation,
    _select_all_seller_conversations,
    _seller_inbox_url,
    _strict_id_match,
    _track_seller_conversation_changes,
    await_bridge_result,
    extract_seller_messages,
    normalize_seller_message,
    _handle_page_events,
    _remember_seller_profiles,
    _sync_seller_profiles,
)


def test_normalizes_seller_center_inbox_message():
    message = normalize_seller_message({
        "message_id": "msg-7",
        "conversation_id": "thread-42",
        "sender_id": "buyer-3",
        "sender_type": "buyer",
        "content": {"text": "Còn hàng không?"},
        "display_name": "Khách TikTok",
        "avatar_url": "https://cdn.example/buyer.png",
        "create_time": 1780000000,
    })

    assert message == {
        "authorId": "buyer-3",
        "displayName": "Khách TikTok",
        "username": "",
        "avatarUrl": "https://cdn.example/buyer.png",
        "threadId": "thread-42",
        "messageId": "msg-7",
        "message": "Còn hàng không?",
        "messageType": "text",
        "createdAt": "1780000000",
        "source": "tiktok_seller_center",
        "mediaUrl": "",
    }


def test_normalizes_message_scraped_from_seller_chat_rendered_state():
    message = normalize_seller_message({
        "messageId": "1737831947109828300",
        "conversation_id": "1737831947109828301",
        "sender_id": "1737831947109828302",
        "sender_type": "buyer",
        "content": "Còn màu đen không?",
        "message_type": "text",
        "created_at": "1780000000123",
        "display_name": "Khách TikTok Shop",
    })

    assert message["messageId"] == "1737831947109828300"
    assert message["threadId"] == "1737831947109828301"
    assert message["authorId"] == "1737831947109828302"
    assert message["message"] == "Còn màu đen không?"
    assert message["createdAt"] == "1780000000123"
    assert message["messageType"] == "text"


def test_seller_center_avatar_fills_missing_message_profile(monkeypatch):
    monkeypatch.setattr("tiktok_bot.SELLER_PROFILE_CACHE", {})
    monkeypatch.setattr("tiktok_bot.SELLER_PROFILE_SYNCED", set())

    pending = _remember_seller_profiles([{
        "customerId": "buyer-9",
        "displayName": "Khách TikTok",
        "avatarUrl": "//cdn.example/buyer.png?size=small",
    }])
    message = normalize_seller_message({
        "message_id": "msg-9",
        "conversation_id": "thread-9",
        "sender_id": "buyer-9",
        "sender_type": "buyer",
        "content": "Chào shop",
    })

    assert pending == [{
        "externalUserId": "buyer-9",
        "avatarUrl": "https://cdn.example/buyer.png?size=small",
        "displayName": "Khách TikTok",
    }]
    assert message["avatarUrl"] == "https://cdn.example/buyer.png?size=small"
    assert message["displayName"] == "Khách TikTok"


def test_seller_center_profiles_are_synced_once_per_avatar(monkeypatch):
    import asyncio

    monkeypatch.setattr("tiktok_bot.SELLER_PROFILE_CACHE", {})
    monkeypatch.setattr("tiktok_bot.SELLER_PROFILE_SYNCED", set())
    posted = []
    monkeypatch.setattr("tiktok_bot._post_profiles", lambda batch: (posted.append(batch) or (200, "{}")))
    rows = [{"customerId": "buyer-1", "avatarUrl": "https://cdn.example/avatar.png"}]

    asyncio.run(_sync_seller_profiles(rows))
    asyncio.run(_sync_seller_profiles(rows))

    assert posted == [[{"externalUserId": "buyer-1", "avatarUrl": "https://cdn.example/avatar.png"}]]


def test_extracts_messages_from_nested_seller_center_event():
    result = extract_seller_messages({
        "event": "new_message",
        "conversation_id": "thread-1",
        "sender_id": "buyer-1",
        "data": {"message_id": "msg-1", "content": "Xin chào"},
    })

    assert len(result) == 1
    assert result[0]["threadId"] == "thread-1"
    assert result[0]["authorId"] == "buyer-1"
    assert result[0]["message"] == "Xin chào"

    wrapped = extract_seller_messages({
        "conversation": {"id": "thread-2"},
        "sender": {"id": "buyer-2", "nickname": "Buyer"},
        "data": {"message_id": "msg-2", "message": "Tư vấn giúp mình"},
    })
    assert len(wrapped) == 1
    assert wrapped[0]["threadId"] == "thread-2"
    assert wrapped[0]["authorId"] == "buyer-2"
    assert wrapped[0]["displayName"] == "Buyer"


@pytest.mark.parametrize("outgoing", [True, 1, "true", "yes"])
def test_ignores_seller_authored_events(outgoing):
    assert normalize_seller_message({
        "message_id": "own-1",
        "conversation_id": "thread-1",
        "sender_id": "seller-1",
        "content": "Seller reply",
        "is_self": outgoing,
    }) is None


def test_ignores_system_cards_and_incomplete_events():
    assert normalize_seller_message({
        "message_id": "card-1", "conversation_id": "thread-1", "sender_id": "system",
        "message_type": "order_card", "content": "Order update",
    }) is None
    assert normalize_seller_message({"message_id": "incomplete", "content": "Hello"}) is None
    assert extract_seller_messages(b"not-json") == []


def test_http_history_replay_only_accepts_messages_created_after_startup():
    import time

    now = time.time()
    assert _message_is_fresh({"createdAt": str(now)}, now - 2)
    assert not _message_is_fresh({"createdAt": str(now - 3600)}, now - 2)
    assert not _message_is_fresh({"createdAt": ""}, now - 2)


def test_auto_open_only_when_a_conversation_changes_after_baseline():
    seen = {}
    existing = {"id": "chat-room-conversation-list-item-0", "key": '["buyer","avatar"]', "activity": '["buyer hello","21:20"]', "unread": 0}
    assert _track_seller_conversation_changes([existing], seen, baseline=True) == []
    assert _track_seller_conversation_changes([existing], seen) == []

    updated = {**existing, "activity": '["buyer new message","21:21"]', "unread": 1}
    assert _track_seller_conversation_changes([updated], seen) == [updated]
    seen[updated["key"]] = (updated["activity"], updated["unread"])
    assert _track_seller_conversation_changes([updated], seen) == []


def test_auto_open_ignores_visual_status_change_without_new_activity():
    seen = {'["buyer","avatar"]': ('["buyer hello","21:20"]', 0)}
    status_only_change = {
        "id": "chat-room-conversation-list-item-0",
        "key": '["buyer","avatar"]',
        "activity": '["buyer hello","21:20"]',
        "unread": 0,
    }

    assert _track_seller_conversation_changes([status_only_change], seen) == []


def test_open_conversation_waits_for_chat_composer(monkeypatch):
    import asyncio

    calls = []

    class Card:
        async def evaluate(self, _script):
            return '["buyer","avatar"]'

        async def click(self, *, timeout):
            calls.append(("click", timeout))

    class Page:
        def locator(self, selector):
            assert selector == "#chat-room-conversation-list-item-0"
            return Card()

        async def wait_for_selector(self, selector, *, state, timeout):
            calls.append((selector, state, timeout))

    monkeypatch.setattr("tiktok_bot.time.monotonic", lambda: 10.0)
    row = {"id": "chat-room-conversation-list-item-0", "key": '["buyer","avatar"]'}
    asyncio.run(_open_seller_conversation(Page(), row))

    assert calls == [("click", 5000), ("#chat-input-send-button", "visible", 8000)]


def test_auto_open_detects_a_new_unread_conversation():
    seen = { '["buyer","avatar"]': ('["buyer old","21:20"]', 0) }
    new_row = {"id": "chat-room-conversation-list-item-1", "key": '["other","avatar2"]', "activity": '["other new","21:21"]', "unread": 1}

    assert _track_seller_conversation_changes([new_row], seen) == [new_row]


def test_selects_all_seller_inbox_without_scrolling():
    import asyncio

    row = {"threadId": "thread-1", "customerId": "buyer-1"}
    clicked = []

    class Candidate:
        async def is_visible(self):
            return True

        async def inner_text(self):
            return "Tất cả 4"

        async def bounding_box(self):
            return {"x": 32, "y": 220, "width": 75, "height": 28}

        async def click(self, *, timeout):
            clicked.append(timeout)

    class Locator:
        async def count(self):
            return 1

        def nth(self, _index):
            return Candidate()

    class Page:
        viewport_size = {"width": 1000}

        def get_by_text(self, label, *, exact):
            assert exact is False
            return Locator() if label == "Tất cả" else EmptyLocator()

        async def wait_for_timeout(self, _milliseconds):
            pass

        async def evaluate(self, _script):
            return [row]

    class EmptyLocator:
        async def count(self):
            return 0

    assert asyncio.run(_select_all_seller_conversations(Page())) == [row]
    assert clicked == [5000]


def test_history_import_uses_only_loaded_messages_and_deduplicates_ids(monkeypatch):
    import asyncio

    row = {"threadId": "thread-1", "customerId": "buyer-1"}
    message = {"messageId": "msg-1", "threadId": "thread-1", "customerId": "buyer-1", "createdAt": "1"}
    other_thread = {**message, "messageId": "msg-2", "threadId": "thread-2"}
    messages = [message, message, other_thread]

    class Page:
        async def wait_for_timeout(self, milliseconds):
            assert milliseconds == 350

    async def visible_messages(_page, _row, *, include_outbound):
        assert include_outbound is True
        return messages

    monkeypatch.setattr("tiktok_bot._seller_visible_messages", visible_messages)

    assert asyncio.run(_loaded_seller_history(Page(), row)) == [message]


def test_outbound_finds_conversation_using_the_same_ids_as_inbox_monitor():
    import asyncio

    class Page:
        async def evaluate(self, _script):
            return [
                {"id": "chat-room-conversation-list-item-0", "threadId": "thread-1", "customerId": "buyer-1"},
                {"id": "chat-room-conversation-list-item-1", "threadId": "thread-2", "customerId": "buyer-2"},
            ]

    match = asyncio.run(_strict_id_match(Page(), "thread-2", "buyer-2"))
    assert match == {"rowId": "chat-room-conversation-list-item-1", "recipientMatches": True}
    assert asyncio.run(_strict_id_match(Page(), "thread-2", "wrong-buyer"))["recipientMatches"] is False
    assert asyncio.run(_strict_id_match(Page(), "missing-thread", "buyer-1")) is None


def test_reads_json_from_tiktok_api_paths_without_chat_keywords(monkeypatch):
    import asyncio

    captured = []

    async def inspect(payload, *, recent_only=False, source=""):
        captured.append((payload, recent_only, source))

    class Page:
        handlers = {}

        def on(self, event, callback):
            self.handlers[event] = callback

    class Response:
        url = "https://seller-vn.tiktok.com/api/v2/query/list"
        headers = {"content-type": "application/json; charset=utf-8"}

        async def json(self):
            return {"data": []}

    monkeypatch.setattr("tiktok_bot._inspect_payload", inspect)

    async def exercise():
        page = Page()
        _handle_page_events(page)
        page.handlers["response"](Response())
        await asyncio.sleep(0)

    asyncio.run(exercise())
    assert captured == [({"data": []}, True, "/api/v2/query/list")]


def test_seller_center_url_is_the_only_supported_inbox_host():
    assert _is_seller_chat_url("https://seller-vn.tiktok.com/chat/inbox/current?shop_region=VN")
    assert not _is_seller_chat_url("https://seller-vn.tiktok.com/chat/assistant-v2/chatbot")
    assert not _is_seller_chat_url("https://www.tiktok.com/messages?lang=en")


def test_rejects_personal_tiktok_url_as_inbox_target(monkeypatch):
    monkeypatch.setattr("tiktok_bot.SELLER_INBOX", "https://www.tiktok.com/messages?lang=en")
    with pytest.raises(RuntimeError, match="Seller Center"):
        _seller_inbox_url()


def test_rejects_other_seller_center_chat_routes_as_inbox(monkeypatch):
    monkeypatch.setattr("tiktok_bot.SELLER_INBOX", "https://seller-vn.tiktok.com/chat/assistant-v2/chatbot")
    with pytest.raises(RuntimeError, match="/chat/inbox/"):
        _seller_inbox_url()


def test_bridge_timeout_reports_delivery_unknown():
    from concurrent.futures import Future

    pending = Future()
    with pytest.raises(TikTokDeliveryUnknown, match="chưa xác nhận"):
        await_bridge_result(pending, timeout=0.001)
    pending.cancel()
