import asyncio
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import meta_business_suite_bridge as bridge
import connector_pairing
from meta_business_suite_bridge import (
    _control_port,
    _is_channel_inbox_url,
    _message_created_at,
    _meta_conversation_url,
    _meta_inbox_url,
    normalize_meta_history,
    parse_meta_datetime,
)


def test_meta_inbox_route_preserves_only_business_and_asset_context():
    url = _meta_inbox_url(
        "instagram",
        "https://business.facebook.com/latest/inbox/all?business_id=12&asset_id=34&selected_item_id=private",
    )

    assert url == "https://business.facebook.com/latest/inbox/instagram_direct?business_id=12&asset_id=34"


def test_meta_conversation_url_selects_exact_thread_without_crossing_inboxes():
    url = _meta_conversation_url(
        "instagram",
        "https://business.facebook.com/latest/inbox/instagram_direct?asset_id=34&business_id=12&mailbox_id=34&thread_type=IG_MESSAGE",
        "thread/with space",
    )

    assert url == "https://business.facebook.com/latest/inbox/instagram_direct?business_id=12&asset_id=34&mailbox_id=34&thread_type=IG_MESSAGE&selected_item_id=thread%2Fwith+space"


def test_instagram_connector_only_reads_the_instagram_direct_inbox():
    instagram_url = "https://business.facebook.com/latest/inbox/instagram_direct?asset_id=34&thread_type=IG_MESSAGE"
    messenger_url = "https://business.facebook.com/latest/inbox/messenger?asset_id=34"

    assert _is_channel_inbox_url("instagram", instagram_url)
    assert not _is_channel_inbox_url("instagram", messenger_url)
    assert not _is_channel_inbox_url("facebook", instagram_url)


@pytest.mark.parametrize(
    ("executable", "channel"),
    [("SmartMerchantMessenger.exe", "facebook"), ("SmartMerchantInstagram.exe", "instagram")],
)
def test_meta_connector_executables_select_their_own_channel(monkeypatch, executable, channel):
    monkeypatch.setattr(bridge.sys, "frozen", True, raising=False)
    monkeypatch.setattr(bridge.sys, "executable", rf"C:\connector\{executable}")
    monkeypatch.delenv("SMART_MERCHANT_CHANNEL_TYPE", raising=False)

    assert bridge._select_channel_type() == channel


def test_meta_vietnamese_timestamp_is_converted_from_local_timezone_to_utc():
    timestamp = parse_meta_datetime(
        "22:01 8 Tháng 9, 2026",
        now=datetime(2026, 10, 6, 12, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")),
    )

    assert timestamp == "2026-09-08T15:01:00+00:00"


def test_meta_english_month_first_timestamp_is_supported():
    timestamp = parse_meta_datetime(
        "10:05 Sep 11, 2026",
        now=datetime(2026, 10, 6, 12, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")),
    )

    assert timestamp == "2026-09-11T03:05:00+00:00"


def test_each_meta_message_uses_its_own_timestamp_over_the_date_separator_time():
    current = datetime(2026, 10, 6, 12, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))

    timestamp = _message_created_at({"dateLabel": "Hôm qua 09:00", "timestamp": "10:30"}, now=current)

    assert timestamp == "2026-10-05T03:30:00+00:00"


def test_meta_date_separator_is_not_falsely_reused_as_each_message_time():
    assert _message_created_at({"dateLabel": "21:47 8 Tháng 9, 2026"}) is None


def test_meta_phone_number_in_message_body_is_not_a_timestamp():
    assert _message_created_at({"message": "Gọi mình số 0384873734", "dateLabel": "21:47 8 Tháng 9, 2026"}) is None


def test_meta_message_timestamp_supports_unix_milliseconds():
    assert parse_meta_datetime("1791284400000") == "2026-10-06T11:00:00+00:00"


@pytest.mark.parametrize(("channel", "port"), [("facebook", 8093), ("instagram", 8094)])
def test_meta_connectors_use_separate_outbound_ports(monkeypatch, channel, port):
    monkeypatch.delenv("META_MESSENGER_BRIDGE_CONTROL_PORT", raising=False)
    monkeypatch.delenv("META_INSTAGRAM_BRIDGE_CONTROL_PORT", raising=False)

    assert _control_port(channel) == port


def test_meta_outbound_opens_the_exact_thread_and_confirms_send(monkeypatch):
    class Locator:
        def __init__(self, page, selector):
            self.page = page
            self.selector = selector

        async def fill(self, value):
            self.page.filled = value

        async def click(self, **_kwargs):
            self.page.clicked = self.selector

        async def press(self, _key):
            pass

    class Page:
        url = "https://business.facebook.com/latest/inbox/instagram_direct?asset_id=34&thread_type=IG_MESSAGE&selected_item_id=old-thread"
        filled = ""
        clicked = ""

        def is_closed(self):
            return False

        async def goto(self, url, **_kwargs):
            self.url = url

        async def wait_for_timeout(self, _milliseconds):
            pass

        async def evaluate(self, script, *_args):
            if "data-smart-merchant-meta-composer" in script and "const editors" in script:
                return {"hasButton": True}
            return {"empty": True, "messageId": "message-sent-7"}

        def locator(self, selector):
            return Locator(self, selector)

    page = Page()
    monkeypatch.setattr(bridge, "CONTROL_PAGE", page)
    monkeypatch.setenv("SMART_MERCHANT_CHANNEL_TYPE", "instagram")

    result = asyncio.run(bridge._send_meta_message("target-thread", "Chào bạn", "buyer-1"))

    assert "selected_item_id=target-thread" in page.url
    assert "instagram_direct" in page.url
    assert page.filled == "Chào bạn"
    assert page.clicked == '[data-smart-merchant-meta-send="active"]'
    assert result == {"status": "sent", "message_id": "message-sent-7", "threadId": "target-thread"}


def test_meta_static_inbox_heading_is_not_used_as_customer_name():
    assert bridge._usable_meta_name(" Giới thiệu ") == ""
    assert bridge._usable_meta_name("Nguyễn An") == "Nguyễn An"


def test_meta_conversation_opens_by_matching_row_and_waits_for_selected_thread(monkeypatch):
    class Page:
        async def evaluate(self, script, label):
            self.script = script
            self.label = label
            return True

        async def wait_for_timeout(self, _milliseconds):
            return None

    ids = iter(("previous-thread", "selected-thread"))
    monkeypatch.setattr(bridge, "_active_thread_id", lambda _page: asyncio.sleep(0, result=next(ids)))
    page = Page()
    row = {"index": 14, "label": "Buyer Name\nLatest message"}

    thread_id = asyncio.run(bridge._open_meta_conversation(page, row))

    assert thread_id == "selected-thread"
    assert page.label == row["label"]
    assert "target.click()" in page.script


def test_meta_history_uses_stable_message_ids_and_separates_direction():
    messages = normalize_meta_history("facebook", "thread-1", "thread-1", "Buyer", [
        {"messageId": "m1", "message": " question ", "direction": "inbound", "avatarUrl": "https://cdn.example/avatar.jpg"},
        {"messageId": "m2", "message": "answer", "direction": "outbound"},
        {"message": "missing stable id", "direction": "inbound"},
    ])

    assert [item["messageId"] for item in messages] == ["m1", "m2"]
    assert [item["direction"] for item in messages] == ["inbound", "outbound"]
    assert messages[0]["threadId"] == messages[0]["customerId"] == "thread-1"
    assert messages[0]["message"] == "question"
    assert messages[0]["avatarUrl"] == "https://cdn.example/avatar.jpg"


def test_instagram_history_keeps_the_profile_avatar_on_each_imported_message():
    messages = normalize_meta_history("instagram", "ig-thread-7", "ig-thread-7", "Ngô Long Thiên", [
        {"messageId": "ig-m1", "message": "Xin chào", "direction": "inbound", "avatarUrl": "https://cdninstagram.example/profile.jpg"},
        {"messageId": "ig-m2", "message": "Tôi cần hỗ trợ", "direction": "outbound", "avatarUrl": "https://cdninstagram.example/profile.jpg"},
    ],)

    # The connector attaches the profile image to every chat row so whichever
    # stable message wins the dedupe path can still update an existing CRM profile.
    assert len(messages) == 2
    assert all(item["threadId"] == "ig-thread-7" for item in messages)
    assert all(item["customerId"] == "ig-thread-7" for item in messages)
    assert all(item["avatarUrl"] == "https://cdninstagram.example/profile.jpg" for item in messages)


def test_meta_profile_backfill_posts_only_profile_data_to_channel_scoped_route(monkeypatch):
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read():
            return b'{"updated":1,"matchedExternalUserIds":["ig-thread-7"]}'

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(bridge, "urlopen", fake_urlopen)

    status, body = bridge._post_meta_profiles(
        "instagram",
        "http://127.0.0.1:8000",
        "connector-token",
        [{"externalUserId": "ig-thread-7", "avatarUrl": "https://cdninstagram.example/profile.jpg"}],
    )

    assert status == 200
    assert json.loads(body)["updated"] == 1
    assert captured == {
        "url": "http://127.0.0.1:8000/api/channels/instagram/profiles",
        "authorization": "Bearer connector-token",
        "payload": {"profiles": [{"externalUserId": "ig-thread-7", "avatarUrl": "https://cdninstagram.example/profile.jpg"}]},
        "timeout": 30,
    }


def test_instagram_avatar_backfill_updates_profiles_without_reading_message_history(monkeypatch, tmp_path):
    row = {
        "index": 0,
        "label": "Ngô Long Thiên\nKhỏe không?",
        "displayName": "Ngô Long Thiên",
        "avatarUrl": "https://cdninstagram.example/profile.jpg",
    }

    class Page:
        async def evaluate(self, *_args):
            return None

        async def wait_for_timeout(self, _milliseconds):
            return None

    async def rows(_page):
        return [row]

    async def open_thread(_page, _row, _channel):
        return "ig-thread-31"

    async def scroll_list(_page):
        return {"top": 300, "client": 300, "height": 300}

    posted = []
    monkeypatch.setattr(bridge, "_conversation_rows", rows)
    monkeypatch.setattr(bridge, "_open_meta_conversation", open_thread)
    monkeypatch.setattr(bridge, "_active_avatar_url", lambda *_args: asyncio.sleep(0, result=""))
    monkeypatch.setattr(bridge, "_scroll_meta_list", scroll_list)
    monkeypatch.setattr(bridge, "_post_meta_profiles", lambda *args: posted.append(args[-1]) or (
        200, '{"updated":1,"matchedExternalUserIds":["ig-thread-31"]}'
    ))

    checkpoint_path = tmp_path / "avatar-checkpoint.json"
    result = asyncio.run(bridge._scan_instagram_profile_avatars(
        Page(), "http://127.0.0.1:8000", "connector-token", checkpoint_path
    ))

    assert result == {"complete": True, "scanned": 1, "detected": 1, "updated": 1, "missing": 0}
    assert posted == [[{
        "externalUserId": "ig-thread-31",
        "avatarUrl": "https://cdninstagram.example/profile.jpg",
    }]]
    assert connector_pairing.load_history_checkpoint(checkpoint_path)["complete"] is True


def test_incremental_meta_import_does_not_mark_partial_thread_history_complete(monkeypatch, tmp_path):
    async def active_thread(_page):
        return "thread-1"

    async def display_name(_page, _fallback):
        return "Buyer"

    async def visible_rows(*_args):
        return [{
            "messageId": "message-1",
            "message": "hello",
            "direction": "inbound",
            "createdAt": None,
            "threadId": "thread-1",
            "customerId": "thread-1",
            "displayName": "Buyer",
            "messageType": "text",
        }]

    completed = []
    monkeypatch.setattr(bridge, "_active_thread_id", active_thread)
    monkeypatch.setattr(bridge, "_active_display_name", display_name)
    monkeypatch.setattr(bridge, "_active_avatar_url", lambda *_args: asyncio.sleep(0, result=""))
    monkeypatch.setattr(bridge, "_visible_message_rows", visible_rows)
    monkeypatch.setattr(bridge, "_send_history", lambda *_args, **_kwargs: (200, "{}"))
    monkeypatch.setattr(
        bridge,
        "mark_history_thread_complete",
        lambda *args: completed.append(args[2]),
    )

    checkpoint, count = asyncio.run(bridge._import_history(
        object(),
        "facebook",
        "http://localhost:8000",
        "connector-token",
        tmp_path / "checkpoint.json",
        {"completed_threads": []},
        scroll_oldest=False,
    ))

    assert count == 1
    assert checkpoint == {"completed_threads": []}
    assert completed == []


def test_meta_import_does_not_mark_unreadable_empty_history_complete(monkeypatch, tmp_path):
    async def active_thread(_page):
        return "thread-1"

    async def display_name(_page, _fallback):
        return "Buyer"

    completed = []
    monkeypatch.setattr(bridge, "_active_thread_id", active_thread)
    monkeypatch.setattr(bridge, "_active_display_name", display_name)
    monkeypatch.setattr(bridge, "_active_avatar_url", lambda *_args: asyncio.sleep(0, result=""))
    monkeypatch.setattr(bridge, "_visible_message_rows", lambda *_args: asyncio.sleep(0, result=[]))
    monkeypatch.setattr(
        bridge,
        "mark_history_thread_complete",
        lambda *args: completed.append(args[2]),
    )

    with pytest.raises(RuntimeError, match="chưa đọc được tin nhắn lịch sử"):
        asyncio.run(bridge._import_history(
            object(),
            "facebook",
            "http://localhost:8000",
            "connector-token",
            tmp_path / "checkpoint.json",
            {"completed_threads": []},
            scroll_oldest=False,
        ))

    assert completed == []


def test_history_batch_marks_only_explicit_live_inbound_messages(monkeypatch):
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read():
            return b"{}"

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(connector_pairing, "urlopen", fake_urlopen)
    status, detail = connector_pairing.post_history_batch(
        "instagram",
        "http://localhost:8000",
        "connector-token",
        [
            {"messageId": "new-in", "direction": "inbound", "message": "new"},
            {"messageId": "new-out", "direction": "outbound", "message": "reply"},
            {"messageId": "old-in", "direction": "inbound", "message": "old"},
        ],
        live_message_ids={"new-in", "new-out"},
    )

    assert status == 200
    assert detail == "{}"
    assert [item.get("isLive", False) for item in captured["payload"]["messages"]] == [True, False, False]
