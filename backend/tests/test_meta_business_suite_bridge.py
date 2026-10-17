import asyncio
import base64
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


def test_connector_accepts_uploaded_image_bytes_without_fetching_a_url(monkeypatch):
    image = b"\x89PNG\r\n\x1a\n" + b"test-image"
    monkeypatch.setattr(bridge, "_download_vietqr_image", lambda *_: pytest.fail("Uploaded images must not fetch a URL"))
    path = bridge._decode_meta_image({"imageData": base64.b64encode(image).decode(), "filename": "../../secret"})
    try:
        assert path.read_bytes() == image
        assert path.suffix == ".png"
    finally:
        path.unlink()
    for invalid in ("%%%", base64.b64encode(b"not-an-image").decode(), "A" * (12 * 1024 * 1024 + 1)):
        with pytest.raises(ValueError):
            bridge._decode_meta_image({"imageData": invalid})


def test_connector_decodes_audio_bytes_without_a_public_url():
    audio = b"ID3" + b"sample-audio"
    path = bridge._decode_meta_attachment(
        {
            "mediaData": base64.b64encode(audio).decode(),
            "contentType": "audio/mpeg",
            "fileName": "../../voice.mp3",
        },
        "audio",
    )
    try:
        assert path.read_bytes() == audio
        assert path.suffix == ".mp3"
    finally:
        path.unlink()


def test_image_only_send_uses_real_dom_upload_and_excludes_pending_preview(monkeypatch, tmp_path):
    playwright = pytest.importorskip("playwright.async_api")
    image = tmp_path / "photo.png"
    image.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1sAAAAASUVORK5CYII="))

    async def run():
        async with playwright.async_playwright() as runtime:
            if not Path(runtime.chromium.executable_path).exists():
                pytest.skip("Chromium is not installed for the optional DOM check")
            browser = await runtime.chromium.launch(headless=True)
            try:
                page = await browser.new_page(viewport={"width": 1200, "height": 900})
                await page.set_content('''
                  <div data-message-id="incoming"><img src="incoming.png" style="position:absolute;left:300px;top:400px;width:100px;height:100px"></div>
                  <img src="avatar.png" style="position:absolute;left:800px;top:300px;width:30px;height:30px">
                  <div id="preview" style="position:absolute;left:800px;top:620px">
                    <img src="preview.png" style="width:80px;height:80px"><button aria-label="Remove attachment">×</button>
                  </div>
                  <textarea aria-label="Trả lời" style="position:absolute;left:300px;top:750px;width:650px;height:80px"></textarea>
                  <input type="file" accept="image/*" hidden>
                  <button aria-label="Gửi" style="position:absolute;left:960px;top:760px" onclick="
                    if (!document.querySelector('input').files.length) throw Error('Missing image');
                    document.querySelector('#preview').remove();
                    document.querySelector('textarea').value = '';
                    const bubble = document.createElement('div');
                    bubble.setAttribute('data-message-id', 'sent-image');
                    bubble.innerHTML = '<img src=&quot;sent.png&quot; style=&quot;position:absolute;left:700px;top:500px;width:100px;height:100px&quot;>';
                    document.body.append(bubble);
                  ">Gửi</button>
                ''')

                async def active_thread(_):
                    return "thread-1"

                monkeypatch.setattr(bridge, "CONTROL_PAGE", page)
                monkeypatch.setattr(bridge, "_active_thread_id", active_thread)
                monkeypatch.setattr(bridge, "_is_channel_inbox_url", lambda *_: True)
                assert await bridge._visible_outbound_images(page) == []
                result = await bridge._send_meta_message("thread-1", "", "buyer-1", image)
                assert result["status"] == "sent"
                assert len(await bridge._visible_outbound_images(page)) == 1
            finally:
                await browser.close()

    asyncio.run(run())


@pytest.mark.parametrize("channel", ["facebook", "instagram"])
@pytest.mark.parametrize("caption", ["", "Thông tin chuyển khoản CHAT-18"])
@pytest.mark.parametrize("image_delivered", [True, False])
def test_meta_image_delivery_requires_a_sent_image_bubble(monkeypatch, channel, caption, image_delivered):
    class Locator:
        async def fill(self, value):
            page.caption = value

        async def click(self, **_):
            page.clicked = True

        async def press(self, *_):
            pytest.fail("An image must use the Send button")

    class Page:
        url = "https://business.facebook.com/latest/inbox/messenger"
        clicked = False

        def is_closed(self):
            return False

        def locator(self, *_):
            return Locator()

        async def wait_for_timeout(self, *_):
            pass

        async def evaluate(self, script, *_):
            if "positions = new Set()" in script:
                return 0
            if "messageText, existingMessageIds" in script:
                # Seeing a caption alone must never count as successful image delivery.
                return {"empty": True, "messageId": "caption-only-id"}
            return {"hasButton": True, "messageIds": []}

    async def active_thread(_):
        return "thread-1"

    async def image_snapshot(_):
        return ["delivered-image"] if page.clicked and image_delivered else []

    async def attach(_, path, media_type="image"):
        assert path == "photo.jpg"
        assert media_type == "image"

    page = Page()
    monkeypatch.setattr(bridge, "CONTROL_PAGE", page)
    monkeypatch.setattr(bridge, "_active_thread_id", active_thread)
    monkeypatch.setattr(bridge, "_is_channel_inbox_url", lambda *_: True)
    monkeypatch.setattr(bridge, "_visible_outbound_images", image_snapshot)
    monkeypatch.setattr(bridge, "_attach_meta_image", attach)
    monkeypatch.setenv("SMART_MERCHANT_CHANNEL_TYPE", channel)
    if image_delivered:
        result = asyncio.run(bridge._send_meta_message("thread-1", caption, "buyer-1", "photo.jpg"))
        assert result["status"] == "sent"
        assert page.caption == caption
    else:
        with pytest.raises(bridge.MetaDeliveryUnknown):
            asyncio.run(bridge._send_meta_message("thread-1", caption, "buyer-1", "photo.jpg"))


def test_meta_audio_delivery_requires_a_new_outbound_message_marker(monkeypatch):
    class Locator:
        async def fill(self, _value):
            pass

        async def click(self, **_):
            pass

    class Page:
        url = "https://business.facebook.com/latest/inbox/messenger"

        def is_closed(self):
            return False

        def locator(self, *_):
            return Locator()

        async def wait_for_timeout(self, *_):
            pass

        async def evaluate(self, script, *_):
            if "messageText, existingMessageIds" in script:
                return {"empty": True, "messageId": "sent-audio-1"}
            return {"hasButton": True, "messageIds": []}

    page = Page()
    attached = {}

    async def active_thread(_):
        return "thread-1"

    async def attach(_page, path, media_type):
        attached.update(path=path, media_type=media_type)

    async def outbound_text_count(*_):
        return 0

    monkeypatch.setattr(bridge, "CONTROL_PAGE", page)
    monkeypatch.setattr(bridge, "_active_thread_id", active_thread)
    monkeypatch.setattr(bridge, "_is_channel_inbox_url", lambda *_: True)
    monkeypatch.setattr(bridge, "_visible_outbound_text_count", outbound_text_count)
    monkeypatch.setattr(bridge, "_attach_meta_image", attach)
    monkeypatch.setenv("SMART_MERCHANT_CHANNEL_TYPE", "facebook")

    result = asyncio.run(bridge._send_meta_message(
        "thread-1", "Nghe lời nhắn", "buyer-1", "voice.mp3", "audio"
    ))

    assert result["message_id"] == "sent-audio-1"
    assert attached == {"path": "voice.mp3", "media_type": "audio"}


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
            if "positions = new Set()" in script:
                return 0
            if "messageText, existingMessageIds" in script:
                assert "previous.has(id)" in script
                assert _args[0]["existingMessageIds"] == ["old-message"]
                return {"empty": True, "messageId": "message-sent-7"}
            if "const editors" in script or "const editor = document.querySelector('[data-smart-merchant-meta-composer" in script:
                return {"hasButton": True, "messageIds": ["old-message"]}
            raise AssertionError(f"Unexpected browser script: {script[:80]}")

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


def test_meta_outbound_click_timeout_is_ambiguous_and_must_not_retry(monkeypatch):
    class Locator:
        def __init__(self, selector):
            self.selector = selector

        async def fill(self, _value):
            pass

        async def click(self, **_kwargs):
            raise asyncio.TimeoutError("send control changed during click")

        async def press(self, _key):
            raise AssertionError("Do not fall back to Enter after a timed-out click")

    class Page:
        url = "https://business.facebook.com/latest/inbox/instagram_direct?asset_id=34&thread_type=IG_MESSAGE&selected_item_id=target-thread"

        def is_closed(self):
            return False

        async def wait_for_timeout(self, _milliseconds):
            pass

        async def evaluate(self, script, *_args):
            if "positions = new Set()" in script:
                return 0
            if "messageText, existingMessageIds" in script:
                raise AssertionError("A timed-out send must not be retried automatically")
            return {"hasButton": True, "messageIds": []}

        def locator(self, selector):
            return Locator(selector)

    monkeypatch.setattr(bridge, "CONTROL_PAGE", Page())
    monkeypatch.setenv("SMART_MERCHANT_CHANNEL_TYPE", "instagram")

    with pytest.raises(bridge.MetaDeliveryUnknown):
        asyncio.run(bridge._send_meta_message("target-thread", "Chào bạn", "buyer-1"))


def test_meta_outbound_requires_provider_message_id_even_if_composer_clears(monkeypatch):
    class Locator:
        def __init__(self, page, selector):
            self.page = page
            self.selector = selector

        async def fill(self, _value):
            pass

        async def click(self, **_kwargs):
            pass

        async def press(self, _key):
            pass

    class Page:
        url = "https://business.facebook.com/latest/inbox/instagram_direct?asset_id=34&thread_type=IG_MESSAGE&selected_item_id=target-thread"

        def is_closed(self):
            return False

        async def wait_for_timeout(self, _milliseconds):
            pass

        async def evaluate(self, script, *_args):
            if "positions = new Set()" in script:
                return 0
            if "messageText, existingMessageIds" in script:
                return {"empty": True, "messageId": ""}
            if "const editors" in script or "const editor = document.querySelector('[data-smart-merchant-meta-composer" in script:
                return {"hasButton": True, "messageIds": []}
            raise AssertionError(f"Unexpected browser script: {script[:80]}")

        def locator(self, selector):
            return Locator(self, selector)

    monkeypatch.setattr(bridge, "CONTROL_PAGE", Page())
    monkeypatch.setenv("SMART_MERCHANT_CHANNEL_TYPE", "instagram")

    with pytest.raises(bridge.MetaDeliveryUnknown):
        asyncio.run(bridge._send_meta_message("target-thread", "Chào bạn", "buyer-1"))


def test_meta_outbound_accepts_new_visible_bubble_without_provider_message_id(monkeypatch):
    class Locator:
        def __init__(self, page, selector):
            self.page = page
            self.selector = selector

        async def fill(self, _value):
            pass

        async def click(self, **_kwargs):
            pass

        async def press(self, _key):
            pass

    class Page:
        url = "https://business.facebook.com/latest/inbox/messenger?selected_item_id=target-thread"

        def __init__(self):
            self.visible_bubbles = 0

        def is_closed(self):
            return False

        async def wait_for_timeout(self, _milliseconds):
            pass

        async def evaluate(self, script, *_args):
            if "positions = new Set()" in script:
                self.visible_bubbles += 1
                return 1 if self.visible_bubbles == 1 else 2
            if "messageText, existingMessageIds" in script:
                return {"empty": True, "messageId": ""}
            if "const editors" in script or "const editor = document.querySelector('[data-smart-merchant-meta-composer" in script:
                return {"hasButton": True, "messageIds": []}
            raise AssertionError(f"Unexpected browser script: {script[:80]}")

        def locator(self, selector):
            return Locator(self, selector)

    monkeypatch.setattr(bridge, "CONTROL_PAGE", Page())
    monkeypatch.setenv("SMART_MERCHANT_CHANNEL_TYPE", "facebook")

    result = asyncio.run(bridge._send_meta_message("target-thread", "Chào bạn", "buyer-1"))

    assert result["status"] == "sent"
    assert result["threadId"] == "target-thread"
    assert result["message_id"].startswith("meta-ui:target-thread:")


def test_visible_meta_rows_deduplicate_nested_ids_but_keep_distinct_bubbles():
    rows = [
        {"messageId": "bubble-id", "message": "Trả lời đã gửi\nĐã gửi Người gửi: Shop", "direction": "outbound", "bubbleX": 650, "bubbleY": 420},
        {"messageId": "status-id", "message": "Trả lời đã gửi\nĐã gửi Người gửi: Shop", "direction": "outbound", "bubbleX": 650, "bubbleY": 420},
        {"messageId": "same-text-next-bubble", "message": "Trả lời đã gửi", "direction": "outbound", "bubbleX": 650, "bubbleY": 500},
    ]

    assert [row["messageId"] for row in bridge._dedupe_visible_message_rows(rows)] == [
        "bubble-id", "same-text-next-bubble",
    ]


def test_meta_static_inbox_heading_is_not_used_as_customer_name():
    assert bridge._usable_meta_name(" Giới thiệu ") == ""
    for label in ("Chia sẻ dữ liệu", "Trang cá nhân trên Facebook", "Share data", "Facebook profile"):
        assert bridge._usable_meta_name(label) == ""
    assert bridge._usable_meta_name("Nguyễn An") == "Nguyễn An"


def test_meta_dom_prefers_row_name_over_avatar_alt_and_ignores_dialog_headings():
    playwright = pytest.importorskip("playwright.async_api")

    async def run():
        async with playwright.async_playwright() as runtime:
            if not Path(runtime.chromium.executable_path).exists():
                pytest.skip("Chromium is not installed for the optional DOM check")
            browser = await runtime.chromium.launch(headless=True)
            try:
                page = await browser.new_page(viewport={"width": 1200, "height": 900})
                await page.route("**/*", lambda route: route.abort())
                await page.set_content('''
                  <div style="position:absolute;left:50px;top:100px;width:300px;height:400px;overflow:auto">
                    <div role="presentation" style="height:80px;cursor:pointer">
                      <img alt="Trang cá nhân trên Facebook" src="https://scontent.example.test/photo.jpg" style="float:left;width:48px;height:48px">
                      <div>Phú Lê</div><div>Xin chào</div>
                    </div><div style="height:600px"></div>
                  </div>
                  <h2 style="position:absolute;left:500px;top:100px">Chia sẻ dữ liệu</h2>
                  <div role="dialog"><h2 style="position:absolute;left:500px;top:90px">Một hộp thoại</h2></div>
                  <h2 style="position:absolute;left:500px;top:180px">Phú Lê</h2>
                ''')
                rows = await bridge._conversation_rows(page)
                assert len(rows) == 1
                assert rows[0]["displayName"] == "Phú Lê"
                assert await bridge._active_display_name(page, "") == "Phú Lê"
            finally:
                await browser.close()

    asyncio.run(run())


def test_meta_history_scan_runs_on_background_tab_without_navigating_live_inbox(monkeypatch, tmp_path):
    class Page:
        def __init__(self, url=""):
            self.url = url
            self.goto_calls = []
            self.closed = False
            self.brought_to_front = False

        async def goto(self, url, **_kwargs):
            self.url = url
            self.goto_calls.append(url)

        async def wait_for_timeout(self, _milliseconds):
            return None

        async def bring_to_front(self):
            self.brought_to_front = True

        async def close(self):
            self.closed = True

    class Context:
        def __init__(self, history_page):
            self.history_page = history_page

        async def new_page(self):
            return self.history_page

    live_page = Page("https://business.facebook.com/latest/inbox/messenger")
    history_page = Page()
    scanned = []
    completed = []
    monkeypatch.setattr(bridge, "_meta_inbox_url", lambda *_: "https://business.facebook.com/latest/inbox/messenger")
    monkeypatch.setattr(bridge, "_inbox_state", lambda _page: "inbox")
    monkeypatch.setattr(bridge, "_is_channel_inbox_url", lambda *_: True)

    async def scan(page, *_args, **_kwargs):
        scanned.append(page)
        return True

    monkeypatch.setattr(bridge, "_scan_loaded_conversations", scan)
    monkeypatch.setattr(bridge, "mark_history_complete", lambda path: completed.append(path))

    assert asyncio.run(bridge._run_background_history_scan(
        Context(history_page), live_page, "facebook", "http://localhost:8000", "token",
        tmp_path / "checkpoint.json", {},
    )) is True
    assert scanned == [history_page]
    assert history_page.closed is True
    assert live_page.goto_calls == []
    assert live_page.brought_to_front is True
    assert completed == [tmp_path / "checkpoint.json"]


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


def test_meta_conversation_waits_through_stale_selected_id_after_click(monkeypatch):
    class Page:
        async def evaluate(self, _script, _label):
            return True

        async def wait_for_timeout(self, _milliseconds):
            pass

    ids = iter(("previous-thread", "previous-thread", "selected-thread"))
    names = iter(("Old buyer", "Old buyer"))
    monkeypatch.setattr(bridge, "_active_thread_id", lambda _page: asyncio.sleep(0, result=next(ids)))
    monkeypatch.setattr(bridge, "_active_display_name", lambda *_args: asyncio.sleep(0, result=next(names)))

    thread_id = asyncio.run(bridge._open_meta_conversation(
        Page(), {"label": "Buyer Name\nLatest message"}, "facebook"
    ))

    assert thread_id == "selected-thread"


def test_meta_conversation_fails_clearly_when_meta_never_selects_a_thread(monkeypatch):
    class Page:
        async def evaluate(self, _script, _label):
            return True

        async def wait_for_timeout(self, _milliseconds):
            return None

    monkeypatch.setattr(bridge, "_active_thread_id", lambda _page: asyncio.sleep(0, result=""))

    with pytest.raises(RuntimeError, match="chưa cung cấp mã hội thoại"):
        asyncio.run(bridge._open_meta_conversation(Page(), {"label": "Buyer\nLatest message"}, "facebook"))


def test_meta_history_uses_stable_message_ids_and_separates_direction():
    messages = normalize_meta_history("facebook", "thread-1", "thread-1", "Buyer", [
        {"messageId": "m1", "message": " question ", "direction": "inbound", "avatarUrl": "https://cdn.example/avatar.jpg"},
        {"messageId": "m2", "message": "answer", "direction": "outbound"},
        {"messageId": "m3", "message": "answer\nĐã gửi", "direction": "outbound"},
        {"message": "missing stable id", "direction": "inbound"},
    ])

    assert [item["messageId"] for item in messages] == ["m1", "m2", "m3"]
    assert [item["direction"] for item in messages] == ["inbound", "outbound", "outbound"]
    assert messages[0]["threadId"] == messages[0]["customerId"] == "thread-1"
    assert messages[0]["message"] == "question"
    assert messages[2]["message"] == "answer"
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


def test_instagram_history_omits_meta_app_update_notice_but_keeps_contact_details():
    notice = "Hãy dùng ứng dụng mới nhất. Hãy dùng phiên bản mới nhất của ứng dụng Instagram để xem loại tin nhắn này."
    messages = normalize_meta_history("instagram", "ig-thread-7", "ig-thread-7", "Buyer", [
        {"messageId": "ig-notice", "message": notice, "direction": "inbound"},
        {"messageId": "ig-phone", "message": "Số điện thoại: 0901234567", "direction": "inbound"},
        {"messageId": "ig-email", "message": "buyer@example.com", "direction": "inbound"},
    ])

    assert [item["messageId"] for item in messages] == ["ig-phone", "ig-email"]
    assert bridge._is_instagram_system_notice(
        "Please use the latest version of Instagram to view this message."
    )
    assert not bridge._is_instagram_system_notice("Số điện thoại: 0901234567")


def test_vietqr_image_download_accepts_only_bounded_png_from_vietqr(monkeypatch, tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + b"image-data"

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        @staticmethod
        def geturl():
            return "https://img.vietqr.io/image/970403-account.png?amount=1000"

        @staticmethod
        def read(_limit):
            return png

    monkeypatch.setattr(bridge, "urlopen", lambda *_args, **_kwargs: Response())
    path = bridge._download_vietqr_image("https://img.vietqr.io/image/970403-account.png?amount=1000")
    try:
        assert path.read_bytes() == png
    finally:
        path.unlink(missing_ok=True)

    with pytest.raises(ValueError, match="VietQR"):
        bridge._download_vietqr_image("https://img.vietqr.io.attacker.test/image/qr.png")


def test_meta_image_attach_uses_hidden_image_file_input():
    class Locator:
        async def set_input_files(self, path):
            page.uploaded = path

    class Page:
        uploaded = ""

        async def evaluate(self, _script, *_args):
            return {"hasInput": True}

        async def wait_for_timeout(self, _milliseconds):
            pass

        def locator(self, selector):
            assert selector == '[data-smart-merchant-meta-upload="active"]'
            return Locator()

    page = Page()
    asyncio.run(bridge._attach_meta_image(page, "C:/temp/qr.png"))
    assert page.uploaded == "C:/temp/qr.png"


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
        return ""

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
    monkeypatch.setattr(
        bridge,
        "_send_history",
        lambda *_args, **_kwargs: (200, bridge.json.dumps({
            "status": "received", "imported": 1, "duplicates": 0, "skipped": 0,
        })),
    )
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
        thread_id="thread-1",
    ))

    assert count == 1
    assert checkpoint == {"completed_threads": []}
    assert completed == []


def test_meta_import_rejects_crm_receipt_that_skips_messages(monkeypatch, tmp_path):
    async def visible_rows(*_args):
        return [{
            "messageId": "message-1", "message": "hello", "direction": "inbound",
            "threadId": "thread-1", "customerId": "thread-1",
        }]

    monkeypatch.setattr(bridge, "_active_thread_id", lambda _page: asyncio.sleep(0, result="thread-1"))
    monkeypatch.setattr(bridge, "_active_display_name", lambda *_args: asyncio.sleep(0, result="Buyer"))
    monkeypatch.setattr(bridge, "_active_avatar_url", lambda *_args: asyncio.sleep(0, result=""))
    monkeypatch.setattr(bridge, "_visible_message_rows", visible_rows)
    monkeypatch.setattr(
        bridge,
        "_send_history",
        lambda *_args, **_kwargs: (200, bridge.json.dumps({
            "status": "received", "imported": 0, "duplicates": 0, "skipped": 1,
        })),
    )

    with pytest.raises(RuntimeError, match="bỏ qua 1"):
        asyncio.run(bridge._import_history(
            object(), "facebook", "http://localhost:8000", "connector-token",
            tmp_path / "checkpoint.json", {"completed_threads": []},
            scroll_oldest=False,
        ))


def test_meta_history_only_marks_messages_after_connector_start_as_live(monkeypatch, tmp_path):
    cutoff = 1_700_000_000
    captured = {}

    async def active_thread(_page):
        return "thread-1"

    async def display_name(_page, _fallback):
        return "Buyer"

    async def visible_rows(*_args):
        return [
            {"messageId": "old", "message": "old text", "direction": "inbound", "createdAt": "2023-11-14T22:13:19Z"},
            {"messageId": "new", "message": "new text", "direction": "inbound", "createdAt": "2023-11-14T22:13:21Z"},
        ]

    def send_history(*_args, **kwargs):
        captured.update(kwargs)
        return 200, json.dumps({"status": "received", "imported": 2, "duplicates": 0, "skipped": 0})

    monkeypatch.setattr(bridge, "_active_thread_id", active_thread)
    monkeypatch.setattr(bridge, "_active_display_name", display_name)
    monkeypatch.setattr(bridge, "_active_avatar_url", lambda *_args: asyncio.sleep(0, result=""))
    monkeypatch.setattr(bridge, "_visible_message_rows", visible_rows)
    monkeypatch.setattr(bridge, "_send_history", send_history)

    asyncio.run(bridge._import_history(
        object(), "facebook", "http://localhost:8000", "connector-token",
        tmp_path / "checkpoint.json", {"completed_threads": []},
        scroll_oldest=False, live_after=cutoff,
    ))

    assert captured["live_message_ids"] == {"new"}


def test_changed_meta_conversation_retries_after_transient_thread_id_error(monkeypatch, tmp_path):
    row = {
        "index": 3,
        "label": "Buyer\nnew message",
        "displayName": "Buyer",
        "avatarUrl": "https://cdn.example/avatar.jpg",
    }
    open_attempts = 0
    imports = []

    async def rows(_page):
        return [row]

    async def open_thread(_page, _row, _channel):
        nonlocal open_attempts
        open_attempts += 1
        if open_attempts == 1:
            raise RuntimeError("Meta chưa cung cấp mã hội thoại đang mở")
        return "thread-3"

    async def import_history(*_args, **_kwargs):
        imports.append(True)
        return {"completed_threads": []}, 1

    monkeypatch.setattr(bridge, "_conversation_rows", rows)
    monkeypatch.setattr(bridge, "_open_meta_conversation", open_thread)
    monkeypatch.setattr(bridge, "_import_history", import_history)

    observed = {"3": "previous-row-signature"}
    profile_cache = {}
    checkpoint_path = tmp_path / "checkpoint.json"

    asyncio.run(bridge._sync_changed_conversations(
        object(), "facebook", "http://localhost:8000", "connector-token",
        checkpoint_path, observed, [row], profile_cache,
    ))
    assert observed["3"] == "previous-row-signature"
    assert imports == []

    asyncio.run(bridge._sync_changed_conversations(
        object(), "facebook", "http://localhost:8000", "connector-token",
        checkpoint_path, observed, [row], profile_cache,
    ))
    assert observed["3"] == bridge.hashlib.sha256(row["label"].encode("utf-8")).hexdigest()
    assert imports == [True]

    asyncio.run(bridge._sync_changed_conversations(
        object(), "facebook", "http://localhost:8000", "connector-token",
        checkpoint_path, observed, [row], profile_cache,
    ))
    assert open_attempts == 2
    assert imports == [True]


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
