"""Forward Shopee Seller Chat messages from a local Edge session to Smart Merchant."""

from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime
import hmac
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from connector_pairing import (
    configure_local_connector,
    history_checkpoint_path,
    load_history_checkpoint,
    mark_history_complete,
    mark_history_thread_complete,
    post_history_batch,
    report_connector_status,
)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = Path(__file__).resolve().parent
PACKAGE_DIR = Path(getattr(sys, "_MEIPASS", str(BASE)))
RUNTIME = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "SmartMerchantShopee"
HISTORY_CHECKPOINT: Path | None = None
EDGE_PROFILE = RUNTIME / "edge-profile"
CDP = os.getenv("SHOPEE_CDP_URL", "http://127.0.0.1:9222")
SELLER_CHAT = "https://banhang.shopee.vn/new-webchat/conversations"
BACKEND_URL = ""
CONNECTOR_TOKEN = ""
SEEN_MESSAGE_IDS: dict[str, float] = {}
IN_FLIGHT_MESSAGE_IDS: set[str] = set()
SYNCED_AVATAR_IDS: set[str] = set()
SHOPEE_CONVERSATION_SCAN_COMPLETE = False
CONTROL_SERVER: ThreadingHTTPServer | None = None
CONTROL_LOOP: asyncio.AbstractEventLoop | None = None
CONTROL_PAGE = None
CONTROL_CONTEXT = None
CONTROL_SECRET = ""
CONTROL_SEND_LOCK = Lock()
HISTORY_CAPTURE_ENABLED = False
HISTORY_CAPTURE_THREAD: dict | None = None
HISTORY_CAPTURE_MESSAGES: dict[str, dict] = {}
CONNECTOR_STARTED_AT = time.time()

class ShopeeDeliveryUnknown(RuntimeError):
    """The click may have reached Shopee, but the chat did not confirm it."""


def await_bridge_result(future, timeout: float = 25) -> dict:
    """A slow UI send may still complete; never report a safe-to-retry 502."""
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError as exc:
        raise ShopeeDeliveryUnknown(
            "Shopee chưa xác nhận tin đã gửi; hãy kiểm tra hội thoại trước khi thử lại."
        ) from exc


def extract_avatar_url(value: object, depth: int = 0) -> str:
    if depth > 5:
        return ""
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("//"):
            return "https:" + value
        if value.startswith(("{", "[")):
            try:
                return extract_avatar_url(json.loads(value), depth + 1)
            except (TypeError, ValueError):
                pass
        return value if value.startswith(("https://", "http://")) else ""
    if isinstance(value, dict):
        for key in ("url", "url_list", "avatar_url", "avatarUrl", "portrait", "src", "image_url", "imageUrl", "avatar"):
            if key in value:
                result = extract_avatar_url(value[key], depth + 1)
                if result:
                    return result
    elif isinstance(value, (list, tuple)):
        for item in value:
            result = extract_avatar_url(item, depth + 1)
            if result:
                return result
    return ""


def find_edge() -> Path | None:
    for root in (os.getenv("PROGRAMFILES(X86)", ""), os.getenv("PROGRAMFILES", ""), os.getenv("LOCALAPPDATA", "")):
        candidate = Path(root) / "Microsoft/Edge/Application/msedge.exe"
        if candidate.is_file():
            return candidate
    return None


def cdp_ready() -> bool:
    if not cdp_browser_ready():
        return False
    try:
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


def cdp_browser_ready() -> bool:
    try:
        with urlopen(CDP + "/json/version", timeout=1.5) as response:
            version = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and str(version.get("Browser", "")).startswith("Edg/")
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


def ensure_edge_connection() -> None:
    """Restore the Seller Chat debug endpoint after its Edge process closes."""
    if not cdp_browser_ready():
        start_edge()


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
    sender = next(
        (message.get(key) for key in ("from_user", "sender", "user_info") if isinstance(message.get(key), dict)),
        {},
    )
    avatar_url = next((avatar for value in (
        message.get("from_user_avatar"), message.get("from_avatar"),
        message.get("sender_avatar"), message.get("avatar_url"),
        message.get("avatarUrl"), message.get("avatar"),
        sender.get("avatar_url"), sender.get("avatarUrl"),
        sender.get("avatar"), sender.get("portrait"),
    ) if (avatar := extract_avatar_url(value))), "")
    message_type = str(message.get("type") or message.get("message_type") or "text").strip().lower()
    if not text and message_type == "text":
        return None
    return {
        "authorId": sender_id,
        "displayName": str(message.get("from_user_name") or sender_id),
        "username": str(message.get("from_user_name") or ""),
        "avatarUrl": avatar_url,
        "threadId": conversation_id,
        "messageId": message_id,
        "message": text or f"[{message_type}]",
        "messageType": message_type,
        "createdAt": str(message.get("created_at") or ""),
        "source": str(message.get("source") or "shopee_seller_chat"),
        "mediaUrl": str(message.get("media_url") or ""),
        "channel": "shopee",
    }


def _truthy(value: object) -> bool:
    return value is True or value == 1 or str(value or "").strip().lower() in {"1", "true", "yes"}


def normalize_history_message(message: object, conversation: dict) -> dict | None:
    """Normalize both sides of a Shopee chat while pinning them to its buyer."""
    if not isinstance(message, dict):
        return None
    message_id = str(message.get("id") or message.get("message_id") or message.get("msg_id") or "").strip()
    thread_id = str(message.get("conversation_id") or message.get("conv_id") or "").strip()
    customer_id = str(conversation.get("customerId") or "").strip()
    if not message_id or not thread_id or thread_id != str(conversation.get("threadId") or "") or not customer_id:
        return None
    raw_content = message.get("content")
    try:
        content = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
    except ValueError:
        content = raw_content
    message_type = str(message.get("type") or message.get("message_type") or "text").strip().lower()
    text = str((content.get("text") if isinstance(content, dict) else "") or
               (raw_content if isinstance(raw_content, str) else "") or message.get("text") or "").strip()
    if message_type not in {"text", "image", "video", "audio", "file", "sticker"}:
        return None
    if not text and message_type == "text":
        return None
    return {
        "threadId": thread_id,
        "customerId": customer_id,
        "messageId": message_id,
        "direction": "outbound" if _truthy(message.get("send_by_yourself")) else "inbound",
        "message": text or f"[{message_type}]",
        "messageType": message_type,
        "displayName": str(conversation.get("displayName") or customer_id)[:255],
        "avatarUrl": str(conversation.get("avatarUrl") or "")[:2000],
        "createdAt": str(message.get("created_at") or message.get("create_time") or "")[:100],
        "mediaUrl": str(message.get("media_url") or "")[:2000],
    }


def _is_recent_message(message: dict, since: float) -> bool:
    value = str(message.get("createdAt") or "").strip()
    try:
        timestamp = float(value)
        if timestamp > 100_000_000_000:
            timestamp /= 1000
    except ValueError:
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return False
    return since - 5 <= timestamp <= time.time() + 300


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


def post_profiles(profiles: list[dict]) -> tuple[int, str]:
    request = Request(
        BACKEND_URL + "/api/channels/shopee/profiles",
        data=json.dumps({"profiles": profiles}, ensure_ascii=False).encode("utf-8"),
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


async def sync_visible_avatars(page) -> None:
    try:
        rows = await page.evaluate(
            """() => [...document.querySelectorAll('[data-cy^="webchat-conversation-cell-root"]')]
              .map(root => {
                const key = Object.getOwnPropertyNames(root).find(name => name.startsWith('__reactFiber$'));
                let fiber = key && root[key], conversation = null;
                for (let depth = 0; fiber && depth < 12; depth++, fiber = fiber.return) {
                  const candidate = fiber.memoizedProps?.conversation;
                  if (candidate) { conversation = candidate; break; }
                }
                return conversation ? {
                  externalUserId: String(conversation.to_id || ''),
                  avatar: conversation.to_avatar || root.querySelector('img')?.currentSrc || ''
                } : null;
              }).filter(Boolean)"""
        )
    except Exception:
        return
    profiles = []
    for row in rows:
        external_user_id = str(row.get("externalUserId") or "").strip()
        avatar_url = extract_avatar_url(row.get("avatar"))
        if external_user_id and external_user_id not in SYNCED_AVATAR_IDS and avatar_url:
            profiles.append({"externalUserId": external_user_id, "avatarUrl": avatar_url})
    if not profiles:
        return
    updated = 0
    for start in range(0, len(profiles), 200):
        batch = profiles[start:start + 200]
        status, detail = await asyncio.to_thread(post_profiles, batch)
        if not 200 <= status < 300:
            if detail:
                print(f"⚠️ Chưa đồng bộ được avatar Shopee (HTTP {status}).", flush=True)
            return
        try:
            matched_ids = json.loads(detail).get("matchedExternalUserIds", [])
        except (AttributeError, TypeError, ValueError):
            matched_ids = []
        SYNCED_AVATAR_IDS.update(str(value) for value in matched_ids if value)
        try:
            updated += int(json.loads(detail).get("updated", 0))
        except (TypeError, ValueError):
            pass
    if updated:
        print(f"✅ Đã đồng bộ avatar Shopee cho {updated} khách hàng.", flush=True)


SHOPEE_ALL_TAB_SELECTED_JS = r"""target => {
  for (let node = target; node && node !== document.body; node = node.parentElement) {
    for (const attr of ['aria-selected', 'aria-current', 'aria-pressed']) {
      const value = node.getAttribute(attr);
      if (value !== null) return value === 'true' || value === 'page';
    }
  }
  const other = [...document.querySelectorAll('div')].find(element =>
    element.childElementCount === 0 && element.textContent.trim() === 'Đang Phục Vụ Hôm Nay'
  );
  if (!other) return false;
  const score = element => element.classList.length + (element.parentElement?.classList.length || 0);
  return score(target) > score(other);
}"""

SHOPEE_ALL_BUYERS_EXPANDED_JS = r"""target => {
  const arrow = target.parentElement?.querySelector(':scope > i');
  if (!arrow) return false;
  const transform = getComputedStyle(arrow).transform;
  if (transform === 'none') return true;
  const matrix = new DOMMatrixReadOnly(transform);
  return Math.abs(matrix.a - 1) < 0.01 && Math.abs(matrix.d - 1) < 0.01
    && Math.abs(matrix.b) < 0.01 && Math.abs(matrix.c) < 0.01;
}"""


async def select_all_conversations_tab(page) -> bool:
    tabs = page.get_by_text("Tất cả cuộc trò chuyện", exact=True)
    selected = False
    for index in range(await tabs.count()):
        tab = tabs.nth(index)
        if await tab.is_visible():
            selected = await tab.evaluate(SHOPEE_ALL_TAB_SELECTED_JS)
            if not selected:
                await tab.locator("xpath=..").click()
                await page.wait_for_timeout(300)
                selected = bool(await tab.evaluate(SHOPEE_ALL_TAB_SELECTED_JS))
            break
    if not selected:
        return False

    buyers = page.get_by_text("Tất cả Người mua", exact=True)
    for index in range(await buyers.count()):
        group = buyers.nth(index)
        try:
            if not await group.is_visible():
                continue
            if not await group.evaluate(SHOPEE_ALL_BUYERS_EXPANDED_JS):
                await group.click()
                await page.wait_for_timeout(300)
        except Exception as exc:
            # The main tab is already selected. Seller Chat changes this
            # optional group's markup often; it must not block syncing/replies.
            print(f"ℹ️ Không cần mở nhóm ‘Tất cả Người mua’ để tiếp tục: {type(exc).__name__}.", flush=True)
        break
    return True


async def _shopee_conversation_rows(page) -> list[dict]:
    rows = await page.evaluate(
        r"""() => [...document.querySelectorAll('[data-cy^="webchat-conversation-cell-root"]')]
          .map(root => {
            const key = Object.getOwnPropertyNames(root).find(name => name.startsWith('__reactFiber$'));
            let fiber = key && root[key], conversation = null;
            for (let depth = 0; fiber && depth < 12; depth++, fiber = fiber.return) {
              const candidate = fiber.memoizedProps?.conversation;
              if (candidate) { conversation = candidate; break; }
            }
            if (!conversation?.id || !conversation?.to_id) return null;
            return {
              id: String(conversation.id), threadId: String(conversation.id),
              customerId: String(conversation.to_id),
              displayName: String(conversation.to_name || conversation.to_nickname || conversation.to_id),
              avatar: conversation.to_avatar || root.querySelector('img')?.currentSrc || ''
            };
          }).filter(Boolean)"""
    )
    for row in rows:
        row["avatarUrl"] = extract_avatar_url(row.pop("avatar", ""))
    return rows


async def _scroll_conversation_list(page, direction: str) -> dict | None:
    return await page.evaluate(
        r"""({direction}) => {
          const item = document.querySelector('[data-cy^="webchat-conversation-cell-root"]');
          if (!item) return null;
          let scroller = item;
          while (scroller && scroller !== document.body) {
            // Seller Chat has shipped list wrappers with overflow-y:hidden that
            // still accept scrollTop updates. Check actual scroll dimensions,
            // not only the CSS overflow keyword.
            if (scroller.scrollHeight > scroller.clientHeight + 8) break;
            scroller = scroller.parentElement;
          }
          if (!scroller || scroller === document.body) {
            const documentScroller = document.scrollingElement;
            if (documentScroller && documentScroller.scrollHeight > documentScroller.clientHeight + 8) scroller = documentScroller;
            else return null;
          }
          const before = scroller.scrollTop;
          const delta = Math.max(180, scroller.clientHeight * 0.75);
          scroller.scrollTop = direction === 'reset' ? 0 : direction === 'top' ? Math.max(0, before - delta) : Math.min(scroller.scrollHeight, before + delta);
          return {before, after: scroller.scrollTop, height: scroller.scrollHeight, client: scroller.clientHeight};
        }""",
        {"direction": direction},
    )


async def _wheel_shopee_area(page, area: str, delta_y: int) -> bool:
    """Scroll Seller Chat's virtualized list when its wrapper hides scrollTop."""
    probe = r"""area => {
      const list = area === 'conversations'
        ? document.querySelector('[data-cy^="webchat-conversation-cell-root"]')?.parentElement
        : document.querySelector('#message-virtualized-list') ||
          document.querySelector('[data-cy="webchat-conversation-detail-message-container"]');
      if (!list) return null;
      const bounds = list.getBoundingClientRect();
      const x = Math.max(1, Math.min(innerWidth - 1, bounds.left + bounds.width / 2));
      const y = Math.max(1, Math.min(innerHeight - 1, bounds.top + bounds.height / 2));
      const nodes = area === 'conversations'
        ? [...document.querySelectorAll('[data-cy^="webchat-conversation-cell-root"]')]
        : [...list.querySelectorAll('[data-cy*="message"], [data-cy*="msg"]')];
      const signature = nodes.map(node => {
        const rect = node.getBoundingClientRect();
        return `${node.getAttribute('data-cy') || ''}:${Math.round(rect.top)}:${(node.innerText || '').slice(0, 120)}`;
      }).join('|') || `${list.scrollTop}:${list.scrollHeight}:${(list.innerText || '').slice(0, 500)}`;
      return {x, y, signature};
    }"""
    try:
        before = await page.evaluate(probe, area)
        mouse = getattr(page, "mouse", None)
        if not before or mouse is None:
            return False
        await mouse.move(before["x"], before["y"])
        await mouse.wheel(0, delta_y)
        await page.wait_for_timeout(350)
        after = await page.evaluate(probe, area)
        return bool(after and after["signature"] != before["signature"])
    except Exception:
        return False


async def _all_shopee_conversations(page) -> list[dict]:
    global SHOPEE_CONVERSATION_SCAN_COMPLETE
    SHOPEE_CONVERSATION_SCAN_COMPLETE = False
    rows: dict[str, dict] = {}
    still = 0
    reached_end = False
    moved_at_least_once = False
    await _scroll_conversation_list(page, "reset")
    for _ in range(300):
        for row in await _shopee_conversation_rows(page):
            rows[row["threadId"]] = row
        before_count = len(rows)
        state = await _scroll_conversation_list(page, "bottom")
        moved = bool(state and state["after"] != state["before"])
        if not moved:
            moved = await _wheel_shopee_area(page, "conversations", 650)
        if moved:
            moved_at_least_once = True
            still = 0
        else:
            still += 1
        await page.wait_for_timeout(180)
        if still >= 3:
            # A stalled wheel after observable movement means the virtual list
            # reached its end. With no movement evidence, keep the checkpoint
            # incomplete rather than claiming the current 10 rows are all chats.
            reached_end = bool(
                (state and state["after"] >= state["height"] - state["client"] - 4)
                or moved_at_least_once
            )
            break
    SHOPEE_CONVERSATION_SCAN_COMPLETE = reached_end
    if not reached_end:
        print(
            f"ℹ️ Đã đọc {len(rows)} hội thoại đang tải; danh sách Shopee còn có thể tải thêm, sẽ tiếp tục kiểm tra.",
            flush=True,
        )
    return list(rows.values())


async def _select_shopee_conversation(page, row: dict) -> bool:
    reset = await _scroll_conversation_list(page, "reset")
    if not reset:
        for _ in range(120):
            if not await _wheel_shopee_area(page, "conversations", -650):
                break
    for _ in range(300):
        result = await page.evaluate(
            SHOPEE_CONVERSATION_JS,
            {"threadId": row["threadId"], "recipientId": row["customerId"], "click": True},
        )
        if result and result.get("found"):
            for _ in range(20):
                selected = await page.evaluate(
                    SHOPEE_CONVERSATION_JS,
                    {"threadId": row["threadId"], "recipientId": row["customerId"], "click": False},
                )
                if selected and selected.get("selected"):
                    return True
                await page.wait_for_timeout(200)
            return False
        state = await _scroll_conversation_list(page, "bottom")
        moved = bool(state and state["after"] != state["before"])
        if not moved:
            moved = await _wheel_shopee_area(page, "conversations", 650)
        if not moved:
            return False
        await page.wait_for_timeout(180)
    return False


async def _capture_shopee_history(page, row: dict) -> tuple[list[dict], bool]:
    global HISTORY_CAPTURE_ENABLED, HISTORY_CAPTURE_THREAD, HISTORY_CAPTURE_MESSAGES
    HISTORY_CAPTURE_MESSAGES = {}
    HISTORY_CAPTURE_THREAD = row
    HISTORY_CAPTURE_ENABLED = True
    try:
        await page.evaluate("window.__SMH_SHOPEE_HISTORY_CAPTURE__ = true")
        await page.wait_for_selector(
            "#message-virtualized-list, [data-cy='webchat-conversation-detail-message-container']",
            state="visible",
            timeout=10000,
        )
        await page.wait_for_timeout(700)
        moved_from_newest = False
        no_movement = 0
        complete = False
        for _ in range(120):
            state = await page.evaluate(
                r"""() => {
                  const list = document.querySelector('#message-virtualized-list') ||
                    document.querySelector('[data-cy="webchat-conversation-detail-message-container"]');
                  if (!list) return null;
                  let scroller = list;
                  while (scroller && scroller !== document.body) {
                    if (scroller.scrollHeight > scroller.clientHeight + 8) break;
                    scroller = scroller.parentElement;
                  }
                  if (!scroller || scroller === document.body || scroller.scrollHeight <= scroller.clientHeight + 8) return null;
                  const before = scroller.scrollTop;
                  scroller.scrollTop = Math.max(0, before - Math.max(160, scroller.clientHeight * 0.75));
                  return {before, after: scroller.scrollTop, height: scroller.scrollHeight, client: scroller.clientHeight};
                }"""
            )
            moved = bool(state and state["after"] != state["before"])
            if state and state["after"] <= 1:
                complete = True
                break
            if not moved:
                moved = await _wheel_shopee_area(page, "messages", -700)
            if moved:
                moved_from_newest = True
                no_movement = 0
            else:
                no_movement += 1
                if moved_from_newest and no_movement >= 3:
                    # The scroll gesture worked, then stopped at the top.
                    complete = True
                    break
                if no_movement >= 5:
                    break
            await page.wait_for_timeout(400)
        await page.evaluate("window.__SMH_SHOPEE_HISTORY_CAPTURE__ = false")
        messages = sorted(HISTORY_CAPTURE_MESSAGES.values(), key=lambda item: str(item.get("createdAt") or ""))
        return messages, complete
    finally:
        try:
            await page.evaluate("window.__SMH_SHOPEE_HISTORY_CAPTURE__ = false")
        except Exception:
            pass
        HISTORY_CAPTURE_ENABLED = False
        HISTORY_CAPTURE_THREAD = None


async def _sync_initial_shopee_history(page) -> None:
    checkpoint = load_history_checkpoint(HISTORY_CHECKPOINT)
    if checkpoint.get("complete"):
        return
    print("📚 Đang quét lịch sử Shopee Seller Chat để nhập an toàn vào CRM…", flush=True)
    rows = await _all_shopee_conversations(page)
    if not rows:
        raise RuntimeError("Chưa đọc được danh sách hội thoại Shopee; lịch sử chưa được đánh dấu hoàn tất.")
    completed = set(str(value) for value in checkpoint.get("completed_threads", []))
    every_thread_complete = True
    for row in rows:
        if row["threadId"] in completed:
            continue
        if not await _select_shopee_conversation(page, row):
            every_thread_complete = False
            print(f"⚠️ Chưa mở được hội thoại Shopee {row['displayName']}; sẽ thử lại ở lần quét sau.", flush=True)
            continue
        messages, history_complete = await _capture_shopee_history(page, row)
        if not messages:
            every_thread_complete = False
            print(f"⚠️ Chưa tải được tin cũ của {row['displayName']}; hội thoại chưa được đánh dấu hoàn tất.", flush=True)
            continue
        for start in range(0, len(messages), 100):
            status, detail = await asyncio.to_thread(
                post_history_batch, "shopee", BACKEND_URL, CONNECTOR_TOKEN, messages[start:start + 100]
            )
            if not 200 <= status < 300:
                raise RuntimeError(f"CRM từ chối lô lịch sử Shopee (HTTP {status}): {detail[:160]}")
        if history_complete:
            checkpoint = mark_history_thread_complete(HISTORY_CHECKPOINT, checkpoint, row["threadId"])
            completed.add(row["threadId"])
            print(f"✅ Đã nhập lịch sử Shopee của {row['displayName']} ({len(messages)} tin).", flush=True)
        else:
            every_thread_complete = False
            print(f"ℹ️ Đã nhập {len(messages)} tin Shopee đang tải của {row['displayName']}; còn lịch sử cũ, sẽ tiếp tục quét.", flush=True)
    if SHOPEE_CONVERSATION_SCAN_COMPLETE and every_thread_complete and all(row["threadId"] in completed for row in rows):
        mark_history_complete(HISTORY_CHECKPOINT)
        print("✅ Đã quét xong các hội thoại lịch sử Shopee hiện có.", flush=True)
    else:
        print("✅ Đã nhập lịch sử các hội thoại Shopee hiện đang tải; sẽ tiếp tục khi Seller Chat hiện thêm hội thoại.", flush=True)


async def deliver(message: dict | None) -> None:
    if not message:
        return
    now = time.monotonic()
    if len(SEEN_MESSAGE_IDS) > 10000:
        SEEN_MESSAGE_IDS.clear()
    if message["messageId"] in SEEN_MESSAGE_IDS and now - SEEN_MESSAGE_IDS[message["messageId"]] < 3600:
        return
    if message["messageId"] in IN_FLIGHT_MESSAGE_IDS:
        return
    IN_FLIGHT_MESSAGE_IDS.add(message["messageId"])
    try:
        status, detail = await asyncio.to_thread(post_message, message)
        if 200 <= status < 300:
            SEEN_MESSAGE_IDS[message["messageId"]] = now
    finally:
        IN_FLIGHT_MESSAGE_IDS.discard(message["messageId"])
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
  const avatarUrl = (value) => {
    if (typeof value === 'string') {
      const text = value.trim();
      return text.startsWith('//') ? `https:${text}` : (/^https?:\/\//i.test(text) ? text : '');
    }
    if (Array.isArray(value)) {
      for (const item of value) { const url = avatarUrl(item); if (url) return url; }
    } else if (value && typeof value === 'object') {
      for (const key of ['url', 'url_list', 'avatar_url', 'avatarUrl', 'portrait', 'src', 'image_url', 'imageUrl', 'avatar']) {
        const url = avatarUrl(value[key]); if (url) return url;
      }
    }
    return '';
  };
  const emit = (candidate) => {
    const message = parse(candidate);
    if (!message || typeof message !== 'object') return;
    const messageId = message.id || message.message_id || message.msg_id;
    const conversationId = message.conversation_id || message.conv_id;
    const senderId = message.from_id || message.sender_id || message.from_user_id;
    if (!messageId || !conversationId || !senderId) return;
    const isSelf = [true, 1, 'true', 'yes'].includes(message.send_by_yourself) || message.send_by_yourself === '1';
    const rawContent = message.content;
    const content = parse(rawContent);
    const messageText = (content && typeof content === 'object' ? content.text : '') ||
      (typeof rawContent === 'string' ? rawContent : '') || message.text || '';
    const sender = message.from_user || message.sender || message.user_info || {};
    const type = String(message.type || message.message_type || 'text');
    if (!messageText && type === 'text') return;
    const safe = {
      id: String(messageId), conversation_id: String(conversationId),
      from_id: String(senderId), from_user_name: String(message.from_user_name || ''),
      from_user_avatar: avatarUrl(message.from_user_avatar || message.from_avatar || message.sender_avatar ||
        message.avatar_url || message.avatarUrl || message.avatar || sender.avatar_url ||
        sender.avatarUrl || sender.avatar || sender.portrait || ''),
      type, content: {text: String(messageText)}, created_at: String(message.created_at || ''),
      source: String(message.source || ''), send_by_yourself: isSelf,
      media_url: String(message.media_url || '')
    };
    if (window.__SMH_SHOPEE_HISTORY_CAPTURE__) console.log('__SMH_SHOPEE_HISTORY__' + JSON.stringify(safe));
    if (isSelf) return;
    console.log('__SMH_SHOPEE__' + JSON.stringify(safe));
  };
  const inspect = (data) => {
    const event = parse(data);
    if (!event || typeof event !== 'object') return;
    for (const envelope of [event, parse(event.payload), parse(event.data)]) {
      if (envelope && envelope.message_content) {
        const content = parse(envelope.message_content);
        if (content && typeof content === 'object') emit({...envelope, ...content});
      }
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


SHOPEE_CONVERSATION_JS = r"""({threadId, recipientId, click}) => {
  const roots = [...document.querySelectorAll('[data-cy^="webchat-conversation-cell-root"]')];
  for (const root of roots) {
    const fiberKey = Object.getOwnPropertyNames(root).find(key => key.startsWith('__reactFiber$'));
    let fiber = fiberKey && root[fiberKey], props = null, conversation = null;
    for (let depth = 0; fiber && depth < 12; depth++, fiber = fiber.return) {
      const candidate = fiber.memoizedProps;
      if (candidate && candidate.conversation) { props = candidate; conversation = candidate.conversation; break; }
    }
    if (!conversation || String(conversation.id || '') !== threadId) continue;
    if (recipientId && String(conversation.to_id || '') !== recipientId) return {found: false, mismatch: true};
    if (click && root.getAttribute('data-cy') !== 'webchat-conversation-cell-root-current') {
      const reactKey = Object.getOwnPropertyNames(root).find(key => key.startsWith('__reactProps$'));
      const onClick = reactKey && root[reactKey]?.onClick;
      if (typeof onClick !== 'function') return {found: true, selected: false, clickFailed: true};
      onClick({target: root, nativeEvent: {preventDefault() {}}});
    }
    return {found: true, selected: root.getAttribute('data-cy') === 'webchat-conversation-cell-root-current'};
  }
  return {found: false, mismatch: false};
}"""

SHOPEE_MESSAGE_COUNT_JS = r"""text => {
  const list = document.querySelector('#message-virtualized-list') ||
    document.querySelector('[data-cy="webchat-conversation-detail-message-container"]');
  if (!list) return null;
  const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
  return [...list.querySelectorAll('[data-cy="webchat-message-send"] pre > div')].filter(node =>
    normalize([...node.childNodes].filter(child => child.nodeType === Node.TEXT_NODE)
      .map(child => child.textContent).join('')) === normalize(text)
  ).length;
}"""

SHOPEE_MESSAGE_APPEARED_JS = r"""({text, previousCount}) => {
  const list = document.querySelector('#message-virtualized-list') ||
    document.querySelector('[data-cy="webchat-conversation-detail-message-container"]');
  if (!list) return false;
  const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
  const count = [...list.querySelectorAll('[data-cy="webchat-message-send"] pre > div')].filter(node =>
    normalize([...node.childNodes].filter(child => child.nodeType === Node.TEXT_NODE)
      .map(child => child.textContent).join('')) === normalize(text)
  ).length;
  return count > previousCount;
}"""


async def wait_for_message_list(page, text: str) -> int:
    """Shopee renders the selected chat asynchronously after selecting a row."""
    for _ in range(40):
        count = await page.evaluate(SHOPEE_MESSAGE_COUNT_JS, text)
        if count is not None:
            return count
        await page.wait_for_timeout(250)
    raise RuntimeError("Shopee chưa tải xong danh sách tin nhắn của hội thoại đã chọn.")


async def enrich_avatar_from_edge(page, message: dict) -> str:
    for _ in range(5):
        try:
            avatar = await page.evaluate(
                """({threadId, senderId}) => {
                  for (const root of document.querySelectorAll('[data-cy^="webchat-conversation-cell-root"]')) {
                    const key = Object.getOwnPropertyNames(root).find(name => name.startsWith('__reactFiber$'));
                    let fiber = key && root[key], conversation = null;
                    for (let depth = 0; fiber && depth < 12; depth++, fiber = fiber.return) {
                      const candidate = fiber.memoizedProps?.conversation;
                      if (candidate && String(candidate.id || '') === threadId) { conversation = candidate; break; }
                    }
                    if (!conversation || String(conversation.to_id || '') !== senderId) continue;
                    if (conversation.to_avatar) return conversation.to_avatar;
                  }
                  return '';
                }""",
                {"threadId": message["threadId"], "senderId": message["authorId"]},
            )
            avatar_url = extract_avatar_url(avatar)
            if avatar_url:
                return avatar_url
        except Exception:
            return ""
        await page.wait_for_timeout(150)
    return ""


async def send_shopee_message(thread_id: str, text: str, recipient_id: str = "") -> dict:
    """Send text through the logged-in Seller Chat page, only on an exact thread match."""
    global CONTROL_PAGE
    if CONTROL_PAGE is None or CONTROL_PAGE.is_closed():
        CONTROL_PAGE = next(
            (
                page for page in (CONTROL_CONTEXT.pages if CONTROL_CONTEXT is not None else [])
                if not page.is_closed() and page.url.startswith("https://banhang.shopee.vn/new-webchat/")
            ),
            None,
        )
    if CONTROL_PAGE is None or CONTROL_PAGE.is_closed():
        raise RuntimeError("Shopee Edge page chưa sẵn sàng.")
    thread_id = str(thread_id or "").strip()
    text = str(text or "").strip()
    if not thread_id or not text:
        raise ValueError("Thiếu threadId hoặc nội dung tin nhắn.")
    if len(text) > 10000:
        raise ValueError("Tin nhắn Shopee vượt quá 10.000 ký tự.")

    if not await select_all_conversations_tab(CONTROL_PAGE):
        raise RuntimeError("Không mở được tab Tất cả cuộc trò chuyện Shopee; tin chưa được gửi.")
    row = {"threadId": thread_id, "customerId": str(recipient_id or "").strip()}
    if not await _select_shopee_conversation(CONTROL_PAGE, row):
        raise RuntimeError(
            "Không tìm thấy đúng hội thoại trong danh sách Tất cả của Shopee. "
            "Đã kiểm tra theo ID để tránh gửi nhầm khách; hãy xác nhận shop đang đăng nhập đúng."
        )

    await CONTROL_PAGE.wait_for_timeout(500)
    previous_message_count = await wait_for_message_list(CONTROL_PAGE, text)
    composers = CONTROL_PAGE.locator(
        '[data-cy="webchat-conversation-detail-input"] textarea:visible, '
        '[data-cy="webchat-conversation-detail-input"] [contenteditable="true"]:visible'
    )
    count = await composers.count()
    if not count:
        raise RuntimeError("Không tìm thấy ô nhập tin nhắn Shopee.")
    composer = composers.nth(count - 1)
    await composer.fill(text)

    send_icons = CONTROL_PAGE.locator('[data-cy="webchat-conversation-detail-input"] i')
    send_index = await send_icons.evaluate_all(
        """icons => {
          const matches = icons.filter(icon => {
            const key = Object.getOwnPropertyNames(icon).find(name => name.startsWith('__reactProps$'));
            const handler = key && icon[key]?.onClick;
            return typeof handler === 'function' && String(handler).includes('MSG_TYPE_TEXT');
          });
          return matches.length === 1 ? icons.indexOf(matches[0]) : -1;
        }"""
    )
    if send_index < 0:
        raise RuntimeError("Không tìm thấy đúng nút gửi trong ô chat Shopee.")
    await send_icons.nth(send_index).click()
    warning = CONTROL_PAGE.get_by_text("Đã phát hiện phản hồi không phù hợp hoặc dư thừa", exact=False)
    for index in range(await warning.count()):
        if await warning.nth(index).is_visible():
            raise RuntimeError(
                "Shopee cảnh báo phản hồi có thể không phù hợp hoặc bị lặp. Hãy sửa nội dung và xác nhận trực tiếp trên Shopee."
            )
    try:
        await CONTROL_PAGE.wait_for_function(
            "() => { const root=document.querySelector('[data-cy=\"webchat-conversation-detail-input\"]'); const e=root?.querySelector('textarea,[contenteditable=\"true\"]'); return !e || !String(e.value ?? e.innerText ?? '').trim(); }",
            timeout=8000,
        )
    except Exception as exc:
        raise RuntimeError("Shopee chưa xác nhận đã nhận tin gửi; hãy kiểm tra hội thoại trước khi thử lại.") from exc
    try:
        await CONTROL_PAGE.wait_for_function(
            SHOPEE_MESSAGE_APPEARED_JS,
            arg={"text": text, "previousCount": previous_message_count},
            timeout=10000,
        )
    except Exception as exc:
        raise ShopeeDeliveryUnknown(
            "Shopee chưa hiển thị tin nhắn trong hội thoại; trạng thái gửi chưa xác nhận. "
            "Hãy kiểm tra Shopee trước khi thử gửi lại."
        ) from exc
    return {"status": "sent", "message_id": f"shopee-ui:{thread_id}:{time.time_ns()}", "threadId": thread_id}


class _ShopeeControlHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args) -> None:
        return

    def _reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/send":
            self._reply(404, {"detail": "Shopee bridge route not found"})
            return
        provided = self.headers.get("X-Shopee-Bridge-Secret", "")
        if not CONTROL_SECRET or not hmac.compare_digest(str(provided), str(CONTROL_SECRET)):
            self._reply(401, {"detail": "Shopee bridge secret không đúng"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 65536:
                raise ValueError("Payload Shopee không hợp lệ.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Payload Shopee không hợp lệ.")
            if CONTROL_LOOP is None:
                self._reply(503, {"detail": "Shopee connector chưa sẵn sàng."})
                return
            with CONTROL_SEND_LOCK:
                future = asyncio.run_coroutine_threadsafe(
                    send_shopee_message(payload.get("threadId"), payload.get("message"), payload.get("recipientId")),
                    CONTROL_LOOP,
                )
                result = await_bridge_result(future)
            self._reply(200, result)
        except ShopeeDeliveryUnknown as exc:
            self._reply(409, {"code": "delivery_unknown", "detail": str(exc)})
        except ValueError as exc:
            self._reply(400, {"detail": str(exc)})
        except Exception as exc:
            print(f"❌ Shopee outbound bridge: {type(exc).__name__}: {exc}", flush=True)
            self._reply(502, {"detail": str(exc)[:300] or "Không thể gửi tin Shopee."})


def start_control_server(page) -> None:
    global CONTROL_SERVER, CONTROL_LOOP, CONTROL_PAGE, CONTROL_CONTEXT
    CONTROL_LOOP = asyncio.get_running_loop()
    CONTROL_PAGE = page
    CONTROL_CONTEXT = page.context
    if CONTROL_SERVER is not None:
        return
    # Docker Desktop reaches the Windows host through its host-gateway interface.
    # The connector token is required on every send request.
    host = os.getenv("SHOPEE_BRIDGE_CONTROL_HOST", "0.0.0.0")
    port = int(os.getenv("SHOPEE_BRIDGE_CONTROL_PORT", "8092"))
    try:
        CONTROL_SERVER = ThreadingHTTPServer((host, port), _ShopeeControlHandler)
        CONTROL_SERVER.daemon_threads = True
        Thread(target=CONTROL_SERVER.serve_forever, daemon=True).start()
        print(f"Shopee outbound bridge: http://{host}:{port}/send", flush=True)
    except OSError as exc:
        print(f"⚠️ Không mở được Shopee outbound bridge: {type(exc).__name__}: {exc}", flush=True)


async def run() -> None:
    global BACKEND_URL, CONNECTOR_TOKEN, CONTROL_SECRET, CONTROL_PAGE, CONTROL_CONTEXT, HISTORY_CHECKPOINT
    print("SmartMerchantShopee build: two-way replies + Shopee avatars", flush=True)
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise SystemExit("Thiếu Playwright. Chạy: python -m pip install playwright") from exc
    BACKEND_URL, CONNECTOR_TOKEN = configure_local_connector("shopee", RUNTIME, PACKAGE_DIR)
    HISTORY_CHECKPOINT = history_checkpoint_path(RUNTIME, "shopee", CONNECTOR_TOKEN)
    CONTROL_SECRET = CONNECTOR_TOKEN
    async with async_playwright() as playwright:
        while True:
            try:
                await asyncio.to_thread(ensure_edge_connection)
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
                        global HISTORY_CAPTURE_MESSAGES
                        raw = console_message.text
                        history_prefix = "__SMH_SHOPEE_HISTORY__"
                        if raw.startswith(history_prefix) and HISTORY_CAPTURE_ENABLED and HISTORY_CAPTURE_THREAD:
                            try:
                                parsed_history = json.loads(raw[len(history_prefix):])
                            except ValueError:
                                parsed_history = None
                            historical = normalize_history_message(parsed_history, HISTORY_CAPTURE_THREAD)
                            if historical:
                                HISTORY_CAPTURE_MESSAGES[historical["messageId"]] = historical
                        if not raw.startswith("__SMH_SHOPEE__"):
                            return
                        try:
                            parsed = json.loads(raw[len("__SMH_SHOPEE__"):])
                        except ValueError:
                            return
                        incoming = normalize_message(parsed)
                        if incoming and HISTORY_CAPTURE_ENABLED and not _is_recent_message(incoming, CONNECTOR_STARTED_AT):
                            return
                        if incoming and not incoming["avatarUrl"]:
                            incoming["avatarUrl"] = await enrich_avatar_from_edge(page, incoming)
                        await deliver(incoming)

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
                else:
                    try:
                        await page.reload(wait_until="domcontentloaded", timeout=120000)
                    except Exception:
                        pass
                start_control_server(page)
                print("Shopee connector đang chạy. Hãy đăng nhập thủ công trong Edge nếu cần; Ctrl+C để dừng.", flush=True)
                last_avatar_sync = 0.0
                last_history_scan = 0.0
                all_conversations_selected = False
                while cdp_ready() and not page.is_closed():
                    try:
                        selected = await select_all_conversations_tab(page)
                        if selected and not all_conversations_selected:
                            print("✅ Shopee đang theo dõi tab Tất cả cuộc trò chuyện.", flush=True)
                        if selected and time.monotonic() - last_history_scan >= 30:
                            last_history_scan = time.monotonic()
                            try:
                                await _sync_initial_shopee_history(page)
                            except Exception as history_error:
                                print(f"⚠️ Đồng bộ lịch sử Shopee đang dở; đã lưu checkpoint để tiếp tục khi chạy lại: {type(history_error).__name__}: {history_error}", flush=True)
                        all_conversations_selected = selected
                    except Exception as exc:
                        if time.monotonic() - last_avatar_sync > 30:
                            print(f"⚠️ Chưa kiểm tra được hội thoại Shopee: {type(exc).__name__}.", flush=True)
                        all_conversations_selected = False
                    if time.monotonic() - last_avatar_sync >= 30:
                        await sync_visible_avatars(page)
                        last_avatar_sync = time.monotonic()
                    await asyncio.sleep(5)
                print("⚠️ Mất kết nối Edge Seller Chat; đang thử nối lại.", flush=True)
                report_connector_status("shopee", BACKEND_URL, CONNECTOR_TOKEN, state="error", error_code="edge_disconnected")
            except Exception as exc:
                print(f"⚠️ Shopee connector chưa nối lại được Edge: {type(exc).__name__}: {exc}", flush=True)
                report_connector_status("shopee", BACKEND_URL, CONNECTOR_TOKEN, state="error", error_code="edge_reconnect_failed")
                await asyncio.sleep(10)
            finally:
                CONTROL_PAGE = None
                CONTROL_CONTEXT = None


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
    except Exception as exc:
        report_connector_status("shopee", BACKEND_URL, CONNECTOR_TOKEN, state="error", error_code=type(exc).__name__.lower())
        raise
