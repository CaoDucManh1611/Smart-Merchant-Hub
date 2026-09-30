"""Forward Shopee Seller Chat messages from a local Edge session to Smart Merchant."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from connector_pairing import configure_local_connector

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = Path(__file__).resolve().parent
PACKAGE_DIR = Path(getattr(sys, "_MEIPASS", str(BASE)))
RUNTIME = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "SmartMerchantShopee"
EDGE_PROFILE = RUNTIME / "edge-profile"
CDP = os.getenv("SHOPEE_CDP_URL", "http://127.0.0.1:9222")
SELLER_CHAT = "https://banhang.shopee.vn/new-webchat/conversations"
BACKEND_URL = ""
CONNECTOR_TOKEN = ""
SEEN_MESSAGE_IDS: dict[str, float] = {}


def find_edge() -> Path | None:
    for root in (os.getenv("PROGRAMFILES(X86)", ""), os.getenv("PROGRAMFILES", ""), os.getenv("LOCALAPPDATA", "")):
        candidate = Path(root) / "Microsoft/Edge/Application/msedge.exe"
        if candidate.is_file():
            return candidate
    return None


def cdp_ready() -> bool:
    try:
        with urlopen(CDP + "/json/version", timeout=1.5) as response:
            version = json.loads(response.read().decode("utf-8"))
            if response.status != 200 or not str(version.get("Browser", "")).startswith("Edg/"):
                return False
        with urlopen(CDP + "/json/list", timeout=1.5) as response:
            targets = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and any(
                target.get("type") == "page"
                and str(target.get("url", "")).startswith("https://banhang.shopee.vn/")
                for target in targets
                if isinstance(target, dict)
            )
    except Exception:
        return False


def start_edge() -> None:
    edge = find_edge()
    if not edge:
        raise RuntimeError("Không tìm thấy Microsoft Edge.")
    EDGE_PROFILE.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            str(edge),
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=9222",
            f"--user-data-dir={EDGE_PROFILE}",
            "--no-first-run",
            "--no-default-browser-check",
            SELLER_CHAT,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("Đã mở Edge riêng cho Shopee. Đăng nhập thủ công nếu được yêu cầu.", flush=True)
    for _ in range(180):
        if cdp_ready():
            return
        time.sleep(0.5)
    raise RuntimeError("Edge chưa sẵn sàng sau 90 giây. Hãy giữ cửa sổ Edge riêng mở và chạy lại connector.")


def normalize_message(message: object) -> dict | None:
    if not isinstance(message, dict):
        return None
    message_id = str(message.get("id") or message.get("message_id") or message.get("msg_id") or "").strip()
    conversation_id = str(message.get("conversation_id") or message.get("conv_id") or "").strip()
    sender_id = str(message.get("from_id") or message.get("sender_id") or message.get("from_user_id") or "").strip()
    if not message_id or not conversation_id or not sender_id:
        return None
    if str(message.get("send_by_yourself") or "").strip().lower() in {"true", "1", "yes"}:
        return None
    raw_content = message.get("content")
    try:
        content = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
    except ValueError:
        content = raw_content
    text = str(
        (content.get("text") if isinstance(content, dict) else "")
        or (raw_content if isinstance(raw_content, str) else "")
        or message.get("text")
        or ""
    ).strip()
    message_type = str(message.get("type") or message.get("message_type") or "text").strip().lower()
    if not text and message_type == "text":
        return None
    return {
        "authorId": sender_id,
        "displayName": str(message.get("from_user_name") or sender_id),
        "username": str(message.get("from_user_name") or ""),
        "threadId": conversation_id,
        "messageId": message_id,
        "message": text or f"[{message_type}]",
        "messageType": message_type,
        "createdAt": str(message.get("created_at") or ""),
        "source": str(message.get("source") or "shopee_seller_chat"),
        "mediaUrl": str(message.get("media_url") or ""),
        "channel": "shopee",
    }


def post_message(message: dict) -> tuple[int, str]:
    payload = {key: value for key, value in message.items() if key != "channel"}
    request = Request(
        BACKEND_URL + "/api/channels/shopee/incoming",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Authorization": f"Bearer {CONNECTOR_TOKEN}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:300]
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


async def deliver(message: dict | None) -> None:
    if not message:
        return
    now = time.monotonic()
    if len(SEEN_MESSAGE_IDS) > 10000:
        SEEN_MESSAGE_IDS.clear()
    if message["messageId"] in SEEN_MESSAGE_IDS and now - SEEN_MESSAGE_IDS[message["messageId"]] < 3600:
        return
    SEEN_MESSAGE_IDS[message["messageId"]] = now
    status, detail = await asyncio.to_thread(post_message, message)
    print(
        f"{'✅' if 200 <= status < 300 else '❌'} Shopee message {message['messageId']} → CRM HTTP {status}",
        flush=True,
    )
    if not 200 <= status < 300 and detail:
        print(detail, flush=True)


PROBE_JS = r"""
(() => {
  if (window.__SMH_SHOPEE_LISTENER__) return;
  window.__SMH_SHOPEE_LISTENER__ = true;
  const parse = (value) => {
    if (value && typeof value === 'object') return value;
    if (typeof value !== 'string') return null;
    try { return JSON.parse(value); } catch (_) { return null; }
  };
  const emit = (candidate) => {
    const message = parse(candidate);
    if (!message || typeof message !== 'object') return;
    const messageId = message.id || message.message_id || message.msg_id;
    const conversationId = message.conversation_id || message.conv_id;
    const senderId = message.from_id || message.sender_id || message.from_user_id;
    if (!messageId || !conversationId || !senderId) return;
    if ([true, 1, '1', 'true', 'yes'].includes(message.send_by_yourself)) return;
    const rawContent = message.content;
    const content = parse(rawContent);
    const messageText = (content && typeof content === 'object' ? content.text : '') ||
      (typeof rawContent === 'string' ? rawContent : '') || message.text || '';
    const type = String(message.type || message.message_type || 'text');
    if (!messageText && type === 'text') return;
    const safe = {
      id: String(messageId), conversation_id: String(conversationId),
      from_id: String(senderId), from_user_name: String(message.from_user_name || ''),
      type, content: {text: String(messageText)}, created_at: String(message.created_at || ''),
      source: String(message.source || ''), send_by_yourself: Boolean(message.send_by_yourself),
      media_url: String(message.media_url || '')
    };
    console.log('__SMH_SHOPEE__' + JSON.stringify(safe));
  };
  const inspect = (data) => {
    const event = parse(data);
    if (!event || typeof event !== 'object') return;
    for (const envelope of [event, parse(event.payload), parse(event.data)]) {
      if (envelope && envelope.message_content) emit(envelope.message_content);
    }
  };
  // Seller Chat uses a SharedWorker MessagePort; observe the port directly so
  // both `onmessage = ...` and `addEventListener` handlers are covered.
  const NativeSharedWorker = window.SharedWorker;
  if (NativeSharedWorker) {
    window.SharedWorker = new Proxy(NativeSharedWorker, {
      construct(target, args, newTarget) {
        const worker = Reflect.construct(target, args, newTarget);
        try {
          worker.port.addEventListener('message', (event) => { try { inspect(event && event.data); } catch (_) {} });
          worker.port.start();
        } catch (_) {}
        return worker;
      }
    });
  }
  window.addEventListener('message', (event) => { try { inspect(event && event.data); } catch (_) {} }, true);
})();
"""


async def run() -> None:
    global BACKEND_URL, CONNECTOR_TOKEN
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise SystemExit("Thiếu Playwright. Chạy: python -m pip install playwright") from exc
    BACKEND_URL, CONNECTOR_TOKEN = configure_local_connector("shopee", RUNTIME, PACKAGE_DIR)
    if not cdp_ready():
        start_edge()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(CDP)
        if not browser.contexts:
            raise RuntimeError("Edge chưa có browser context.")
        context = browser.contexts[0]
        attached: set[int] = set()

        def attach(page) -> None:
            if id(page) in attached:
                return
            attached.add(id(page))

            async def on_console(console_message) -> None:
                raw = console_message.text
                if not raw.startswith("__SMH_SHOPEE__"):
                    return
                try:
                    parsed = json.loads(raw[len("__SMH_SHOPEE__"):])
                except ValueError:
                    return
                await deliver(normalize_message(parsed))

            page.on("console", lambda event: asyncio.create_task(on_console(event)))

        for page in context.pages:
            attach(page)
            await page.add_init_script(PROBE_JS)
            try:
                await page.evaluate(PROBE_JS)
            except Exception:
                pass

        async def prepare_page(page) -> None:
            attach(page)
            await page.add_init_script(PROBE_JS)
            try:
                await page.evaluate(PROBE_JS)
            except Exception:
                pass

        context.on("page", lambda page: asyncio.create_task(prepare_page(page)))
        page = next((item for item in context.pages if "banhang.shopee.vn" in item.url), None)
        if page is None:
            page = await context.new_page()
            attach(page)
            await page.add_init_script(PROBE_JS)
            await page.goto(SELLER_CHAT, wait_until="domcontentloaded", timeout=120000)
        try:
            await page.reload(wait_until="domcontentloaded", timeout=120000)
        except Exception:
            pass
        print("Shopee connector đang chạy. Hãy đăng nhập thủ công trong Edge nếu cần; Ctrl+C để dừng.", flush=True)
        while True:
            await asyncio.sleep(3600)


def self_test() -> None:
    from playwright.async_api import async_playwright

    if async_playwright is None:
        raise SystemExit("Thiếu thư viện chạy Shopee.")
    driver = Path(__import__("playwright").__file__).parent / "driver" / "node.exe"
    if not driver.is_file():
        raise SystemExit("Thiếu runtime Playwright trong ứng dụng.")
    print("Smart Merchant Shopee: ứng dụng và runtime đã sẵn sàng.")


if __name__ == "__main__" and "--self-test" in sys.argv:
    self_test()
elif __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("Đã dừng Shopee connector.", flush=True)
