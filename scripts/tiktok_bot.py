"""Forward TikTok Shop Seller Center inbox messages through a local Edge session."""

from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from connector_pairing import (
    configure_local_connector,
    history_checkpoint_path,
    load_history_checkpoint,
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
RUNTIME = Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "SmartMerchantTikTok"
HISTORY_CHECKPOINT: Path | None = None
EDGE_PROFILE = RUNTIME / "seller-center-edge-profile"
CDP_PORT = int(os.getenv("TIKTOK_CDP_PORT", "9223"))
CDP = os.getenv("TIKTOK_CDP_URL", f"http://127.0.0.1:{CDP_PORT}").rstrip("/")
SELLER_INBOX = os.getenv(
    "TIKTOK_SELLER_INBOX_URL",
    "https://seller-vn.tiktok.com/chat/inbox/current?shop_region=VN&lang=en",
).strip()
BACKEND_URL = ""
CONNECTOR_TOKEN = ""
CONTROL_SECRET = ""
CONTROL_PORT = int(os.getenv("TIKTOK_BRIDGE_CONTROL_PORT", "8091"))
CONTROL_PAGE = None
CONTROL_CONTEXT = None
CONTROL_LOOP: asyncio.AbstractEventLoop | None = None
CONTROL_SERVER: ThreadingHTTPServer | None = None
CONTROL_SEND_LOCK = Lock()
SEEN_MESSAGE_IDS: dict[str, float] = {}
IN_FLIGHT_MESSAGE_IDS: set[str] = set()
RECENT_OUTBOUND: dict[tuple[str, str], float] = {}
SELLER_PROFILE_CACHE: dict[str, dict] = {}
SELLER_PROFILE_SYNCED: set[tuple[str, str]] = set()
CONNECTOR_STARTED_AT = time.time()
CAPTURE_PROBE_UNTIL = 0.0
CAPTURE_PROBE_REMAINING = 0


class TikTokDeliveryUnknown(RuntimeError):
    """The click may have reached Seller Center, but its UI did not confirm it."""


def await_bridge_result(future, timeout: float = 25) -> dict:
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError as exc:
        raise TikTokDeliveryUnknown(
            "TikTok Shop chưa xác nhận tin đã gửi; hãy kiểm tra hội thoại trước khi thử lại."
        ) from exc


def _first(mapping: dict, *keys: str):
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return _as_text(_first(value, "text", "content", "message", "value"))
    return ""


def _is_true(value: object) -> bool:
    return value is True or value == 1 or str(value or "").strip().lower() in {"1", "true", "yes"}


def _is_outgoing(message: dict) -> bool:
    flags = (
        "send_by_yourself", "is_self", "is_self_message", "is_from_shop",
        "isFromShop", "from_me", "fromMe", "is_outgoing", "isOutgoing",
        "is_sender_shop", "isSellerMessage", "self_message",
    )
    if any(_is_true(message.get(key)) for key in flags):
        return True
    sender_type = str(_first(message, "sender_type", "senderType", "from_type", "role") or "").lower()
    return any(word in sender_type for word in ("seller", "shop", "merchant", "agent", "system"))


def _parse_json(value: object):
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in "[{\"":
            try:
                return json.loads(text)
            except (TypeError, ValueError):
                return None
    return None


def _message_is_fresh(message: dict, since: float) -> bool:
    value = str(message.get("createdAt") or "").strip()
    if not value:
        return False
    try:
        timestamp = float(value)
        if timestamp > 100_000_000_000:
            timestamp /= 1000
    except ValueError:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            timestamp = parsed.timestamp()
        except ValueError:
            return False
    return since - 5 <= timestamp <= time.time() + 300


def normalize_seller_message(message: object, inherited: dict | None = None) -> dict | None:
    """Map a Seller Center message-like record to the CRM connector contract."""
    if not isinstance(message, dict):
        return None
    data = {**(inherited or {}), **message}
    raw_content = _first(data, "message_content", "messageContent", "content", "message")
    nested = _parse_json(raw_content)
    if isinstance(nested, dict):
        data = {**data, **nested}
    message_id = _as_text(_first(data, "message_id", "messageId", "msg_id", "msgId", "id"))
    thread_id = _as_text(_first(
        data, "conversation_id", "conversationId", "conv_id", "convId",
        "thread_id", "threadId", "chat_id", "chatId",
    ))
    sender = _first(data, "sender", "from_user", "fromUser", "author", "buyer")
    sender = sender if isinstance(sender, dict) else {}
    sender_id = _as_text(_first(
        data, "sender_id", "senderId", "from_id", "fromId", "author_id", "authorId",
        "from_user_id", "fromUserId", "buyer_id", "buyerId", "customer_id", "customerId",
    ) or _first(sender, "id", "user_id", "userId", "uid", "sec_uid"))
    text = _as_text(_first(data, "text", "content_text", "contentText", "body", "message_text", "messageText"))
    if not text and isinstance(raw_content, str):
        text = raw_content.strip()
    message_type = str(_first(data, "message_type", "messageType", "msg_type", "type") or "text").strip().lower()
    allowed_types = {"text", "image", "video", "audio", "file", "sticker"}
    if message_type not in allowed_types:
        return None
    if not message_id or not thread_id or not sender_id or _is_outgoing(data):
        return None
    if not text and message_type == "text":
        return None
    if not text:
        text = f"[{message_type}]"
    avatar = _as_text(_first(data, "avatar_url", "avatarUrl", "avatar", "profile_image", "profileImage") or
                      _first(sender, "avatar_url", "avatarUrl", "avatar", "profile_image", "profileImage"))
    display_name = _as_text(_first(data, "display_name", "displayName", "nickname", "nick_name", "name") or
                            _first(sender, "display_name", "displayName", "nickname", "nick_name", "name"))
    username = _as_text(_first(data, "username", "unique_id", "uniqueId", "handle") or
                        _first(sender, "username", "unique_id", "uniqueId", "handle"))
    profile = SELLER_PROFILE_CACHE.get(sender_id, {})
    if not avatar.startswith(("https://", "http://")):
        avatar = str(profile.get("avatarUrl") or "")
    display_name = display_name or str(profile.get("displayName") or "")
    username = username or str(profile.get("username") or "")
    media_url = _as_text(_first(data, "media_url", "mediaUrl", "url", "origin_url", "originUrl"))
    return {
        "authorId": sender_id[:255],
        "displayName": (display_name or username or sender_id)[:255],
        "username": username[:255],
        "avatarUrl": avatar[:2000] if avatar.startswith(("https://", "http://")) else "",
        "threadId": thread_id[:255],
        "messageId": message_id[:255],
        "message": text[:10000],
        "messageType": message_type,
        "createdAt": _as_text(_first(data, "created_at", "createdAt", "timestamp", "create_time", "createTime"))[:100],
        "source": "tiktok_seller_center",
        "mediaUrl": media_url[:2000] if media_url.startswith(("https://", "http://")) else "",
    }


def extract_seller_messages(payload: object) -> list[dict]:
    """Find message records in JSON response/event envelopes without retaining them."""
    root = _parse_json(payload)
    if root is None:
        return []
    found: dict[str, dict] = {}
    visited = 0

    def walk(value, context: dict, depth: int) -> None:
        nonlocal visited
        if depth > 8 or visited > 12000:
            return
        if isinstance(value, list):
            for item in value[:2000]:
                walk(item, context, depth + 1)
            return
        if not isinstance(value, dict):
            return
        visited += 1
        normalized = normalize_seller_message(value, context)
        if normalized:
            found[normalized["messageId"]] = normalized
        # Propagate only identifiers that can describe a message or conversation.
        next_context = dict(context)
        for key in (
            "conversation_id", "conversationId", "conv_id", "convId", "thread_id", "threadId",
            "chat_id", "chatId", "sender_id", "senderId", "from_id", "fromId", "author_id",
            "authorId", "from_user_id", "fromUserId", "buyer_id", "buyerId", "customer_id",
            "customerId", "sender_type", "senderType", "is_self", "is_from_shop", "is_outgoing",
        ):
            if key in value:
                next_context[key] = value[key]
        sender = _first(value, "sender", "from_user", "fromUser", "author", "buyer")
        if isinstance(sender, dict):
            sender_id = _first(sender, "id", "user_id", "userId", "uid", "sec_uid")
            if sender_id not in (None, "", [], {}):
                next_context.setdefault("sender_id", sender_id)
            next_context.setdefault("sender", sender)
        conversation = _first(value, "conversation", "chat", "thread")
        if isinstance(conversation, dict):
            conversation_id = _first(conversation, "conversation_id", "conversationId", "id", "thread_id", "threadId")
            if conversation_id not in (None, "", [], {}):
                next_context.setdefault("conversation_id", conversation_id)
        for child in value.values():
            parsed = _parse_json(child)
            if isinstance(parsed, (dict, list)):
                walk(parsed, next_context, depth + 1)

    walk(root, {}, 0)
    return list(found.values())


def _seller_inbox_url() -> str:
    parsed = urlparse(SELLER_INBOX)
    if parsed.scheme != "https" or parsed.hostname != "seller-vn.tiktok.com" or not parsed.path.startswith("/chat/inbox/"):
        raise RuntimeError("Địa chỉ phải là hộp thư TikTok Shop Seller Center Việt Nam (/chat/inbox/...).")
    return SELLER_INBOX


def _find_edge() -> Path | None:
    for root in (os.getenv("PROGRAMFILES(X86)", ""), os.getenv("PROGRAMFILES", ""), os.getenv("LOCALAPPDATA", "")):
        candidate = Path(root) / "Microsoft/Edge/Application/msedge.exe"
        if candidate.is_file():
            return candidate
    return None


def _cdp_browser_ready() -> bool:
    try:
        with urlopen(CDP + "/json/version", timeout=1.5) as response:
            version = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and str(version.get("Browser", "")).startswith("Edg/")
    except Exception:
        return False


def _start_edge() -> None:
    edge = _find_edge()
    if not edge:
        raise RuntimeError("Không tìm thấy Microsoft Edge.")
    EDGE_PROFILE.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            str(edge), "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={EDGE_PROFILE}", "--no-first-run", "--no-default-browser-check", _seller_inbox_url(),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("Đã mở Edge riêng cho TikTok Shop Seller Center. Hãy đăng nhập thủ công nếu được yêu cầu.", flush=True)
    for _ in range(180):
        if _cdp_browser_ready():
            return
        time.sleep(0.5)
    raise RuntimeError("Edge Seller Center chưa sẵn sàng sau 90 giây.")


def _ensure_edge() -> None:
    if not _cdp_browser_ready():
        _start_edge()


def _post_message(message: dict) -> tuple[int, str]:
    payload = {key: value for key, value in message.items() if key not in {"channel"}}
    request = Request(
        BACKEND_URL + "/api/channels/tiktok/incoming",
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


def _post_profiles(profiles: list[dict]) -> tuple[int, str]:
    request = Request(
        BACKEND_URL + "/api/channels/tiktok/profiles",
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


def _remember_seller_profiles(rows: list[dict]) -> list[dict]:
    pending: dict[str, dict] = {}
    for row in rows:
        customer_id = str(row.get("customerId") or "").strip()
        avatar_url = str(row.get("avatarUrl") or "").strip()
        if avatar_url.startswith("//"):
            avatar_url = "https:" + avatar_url
        if not customer_id or not avatar_url.startswith(("https://", "http://")):
            continue
        profile = {
            "externalUserId": customer_id[:255],
            "avatarUrl": avatar_url[:2000],
        }
        display_name = str(row.get("displayName") or "").strip()
        if display_name:
            profile["displayName"] = display_name[:255]
        SELLER_PROFILE_CACHE[customer_id] = profile
        key = (customer_id, avatar_url)
        if key not in SELLER_PROFILE_SYNCED:
            pending[customer_id] = profile
    return list(pending.values())


async def _sync_seller_profiles(rows: list[dict]) -> None:
    profiles = _remember_seller_profiles(rows)
    for start in range(0, len(profiles), 200):
        batch = profiles[start:start + 200]
        status, detail = await asyncio.to_thread(_post_profiles, batch)
        if not 200 <= status < 300:
            print(f"⚠️ Chưa đồng bộ được {len(batch)} avatar TikTok vào CRM (HTTP {status}).", flush=True)
            if detail:
                print(detail, flush=True)
            return
        SELLER_PROFILE_SYNCED.update(
            (profile["externalUserId"], profile["avatarUrl"]) for profile in batch
        )


async def _deliver(message: dict | None) -> None:
    if not message:
        return
    now = time.monotonic()
    if len(SEEN_MESSAGE_IDS) > 10000:
        SEEN_MESSAGE_IDS.clear()
    if message["messageId"] in SEEN_MESSAGE_IDS and now - SEEN_MESSAGE_IDS[message["messageId"]] < 3600:
        return
    if message["messageId"] in IN_FLIGHT_MESSAGE_IDS:
        return
    outbound_key = (message["threadId"], message["message"])
    if now - RECENT_OUTBOUND.get(outbound_key, 0) < 120:
        return
    IN_FLIGHT_MESSAGE_IDS.add(message["messageId"])
    try:
        status, detail = await asyncio.to_thread(_post_message, message)
        if 200 <= status < 300:
            SEEN_MESSAGE_IDS[message["messageId"]] = now
    finally:
        IN_FLIGHT_MESSAGE_IDS.discard(message["messageId"])
    print(
        f"{'✅' if 200 <= status < 300 else '❌'} TikTok Shop Seller Chat message {message['messageId']} → CRM HTTP {status}",
        flush=True,
    )
    if not 200 <= status < 300 and detail:
        print(detail, flush=True)


async def _inspect_payload(payload: object, *, recent_only: bool = False, source: str = "websocket") -> None:
    messages = extract_seller_messages(payload)
    global CAPTURE_PROBE_REMAINING
    if CAPTURE_PROBE_REMAINING and time.monotonic() <= CAPTURE_PROBE_UNTIL and (
        messages or any(part in source.lower() for part in ("message", "conversation", "chat"))
    ):
        root = _parse_json(payload)
        fields = {"root": list(root)[:16]} if isinstance(root, dict) else {"root_type": type(root).__name__}
        if isinstance(root, dict):
            for key in ("data", "payload", "message", "messages", "result"):
                nested = _parse_json(root.get(key))
                if isinstance(nested, dict):
                    fields[key] = list(nested)[:16]
                elif isinstance(nested, list) and nested and isinstance(nested[0], dict):
                    fields[f"{key}[]"] = list(nested[0])[:16]
        print(f"🔎 Seller Center {source}: parser thấy {len(messages)} tin; tên trường {json.dumps(fields, ensure_ascii=False)}", flush=True)
        CAPTURE_PROBE_REMAINING -= 1
    if recent_only and messages:
        fresh_messages = [message for message in messages if _message_is_fresh(message, CONNECTOR_STARTED_AT)]
        if not fresh_messages:
            print(f"ℹ️ Seller Center có {len(messages)} tin trong lịch sử; bỏ qua vì tin cũ hoặc thiếu thời gian.", flush=True)
        messages = fresh_messages
    for message in messages:
        await _deliver(message)


async def _seller_conversation_rows(page) -> list[dict]:
    return await page.evaluate(
        r"""() => [...document.querySelectorAll('[data-testid="chat.chatroom.conversation_card"]')]
          .map(row => {
            const usernameNode = row.querySelector('[data-testid="chat.chatroom.conversation_card_username"]');
            const username = usernameNode?.innerText?.trim() || '';
            const preview = usernameNode?.parentElement?.parentElement?.nextElementSibling?.querySelector('span')?.innerText?.trim() || '';
            const avatar = row.querySelector('img')?.currentSrc || row.querySelector('img')?.getAttribute('src') || '';
            const unread = Number.parseInt(row.querySelector('.p-badge-number')?.innerText?.trim() || '0', 10) || 0;
            const handlersKey = Object.getOwnPropertyNames(row).find(key => key.startsWith('__reactEventHandlers$'));
            const children = row[handlersKey]?.children;
            const childNodes = Array.isArray(children) ? children : Object.values(children || {});
            const contact = childNodes.map(child => child?.props?.contact).find(Boolean) || {};
            return {
              id: row.id,
              key: JSON.stringify([username, avatar]),
              activity: JSON.stringify([preview, row.querySelector('time')?.innerText?.trim() || '']),
              threadId: String(contact.conversationId || ''),
              customerId: String(contact.pigeonUid || ''),
              displayName: username,
              avatarUrl: avatar,
              unread,
            };
          }).filter(row => row.id && row.key !== '["",""]')"""
    )


async def _seller_visible_messages(page, row: dict, *, include_outbound: bool = False) -> list[dict]:
    return await page.evaluate(
        r"""({threadId, customerId, displayName, avatarUrl, includeOutbound}) =>
          [...document.querySelectorAll('[data-testid="chat.chatroom.message_card"]')]
            .filter(card => card.getClientRects().length)
            .map(card => {
              const node = card.querySelector('.chatd-message');
              const bubble = node?.querySelector(includeOutbound ? '[class*="chatd-bubble-main--"]' : '.chatd-bubble-main--other');
              if (!node || !bubble) return null;
              const instanceKey = Object.getOwnPropertyNames(card).find(key => key.startsWith('__reactInternalInstance$'));
              let fiber = instanceKey && card[instanceKey];
              let message = null;
              for (let depth = 0; fiber && depth < 18; depth++, fiber = fiber.return) {
                for (const props of [fiber.memoizedProps, fiber.pendingProps]) {
                  if (props?.message && typeof props.message === 'object') {
                    message = props.message;
                    break;
                  }
                }
                if (message) break;
              }
              const text = bubble.innerText?.trim() || '';
              const messageId = String(message?.messageServerId || message?.messageId || message?.rawMessage?.serverId || '');
              const senderId = String(message?.sender || customerId || '');
              const actualThreadId = String(message?.rawMessage?.conversationId || threadId || '');
              const direction = bubble.className.includes('--other') ? 'inbound' : 'outbound';
              if (!message || message.msgType !== 1000 || !messageId || !senderId || !actualThreadId || !text) return null;
              if (!includeOutbound && direction !== 'inbound') return null;
              return {
                messageId,
                threadId: actualThreadId,
                customerId,
                direction,
                message: text,
                messageType: 'text',
                createdAt: String(message.createTime || ''),
                displayName,
                avatarUrl,
              };
            }).filter(Boolean)""",
        {**row, "includeOutbound": include_outbound},
    )


async def _select_all_seller_conversations(page) -> list[dict]:
    candidates = []
    viewport_width = (page.viewport_size or {}).get("width", 1920)
    for label in ("Tất cả", "All"):
        locator = page.get_by_text(label, exact=False)
        for index in range(await locator.count()):
            item = locator.nth(index)
            if not await item.is_visible():
                continue
            text = " ".join((await item.inner_text()).split())
            folded_text, folded_label = text.casefold(), label.casefold()
            if folded_text != folded_label and not (
                folded_text.startswith(folded_label + " ")
                and folded_text[len(folded_label):].strip().isdigit()
            ):
                continue
            box = await item.bounding_box()
            if box and box["x"] < viewport_width * 0.4:
                candidates.append((box["x"], box["y"], box["width"] * box["height"], item))
    if not candidates:
        raise RuntimeError("Không tìm thấy mục Tất cả trong hộp thư Seller Center.")
    await min(candidates, key=lambda candidate: (candidate[0], candidate[2], candidate[1]))[3].click(timeout=5000)
    await page.wait_for_timeout(400)
    return await _seller_conversation_rows(page)


async def _loaded_seller_history(page, row: dict) -> list[dict]:
    """Read message cards already rendered by Seller Center; never scroll either pane."""
    await page.wait_for_timeout(350)
    messages = await _seller_visible_messages(page, row, include_outbound=True)
    unique = {
        str(message["messageId"]): message
        for message in messages
        if message.get("messageId")
        and message.get("threadId") == row.get("threadId")
        and message.get("customerId") == row.get("customerId")
    }
    return sorted(unique.values(), key=lambda item: str(item.get("createdAt") or ""))


async def _sync_initial_seller_history(page, visible_rows: list[dict]) -> None:
    checkpoint = load_history_checkpoint(HISTORY_CHECKPOINT)
    rows = [row for row in visible_rows if row.get("threadId") and row.get("customerId")]
    if not rows:
        raise RuntimeError("Seller Center chưa cung cấp được mã khách cho danh sách chat; chưa đánh dấu đồng bộ hoàn tất.")
    print(f"📚 Đang kiểm tra {len(rows)} hội thoại đang tải trong mục Tất cả…", flush=True)
    await _sync_seller_profiles(rows)
    completed = set(str(value) for value in checkpoint.get("completed_threads", []))
    for original in rows:
        thread_id = str(original["threadId"])
        if thread_id in completed:
            continue
        row = next((
            candidate for candidate in await _seller_conversation_rows(page)
            if candidate.get("threadId") == thread_id
            and candidate.get("customerId") == original.get("customerId")
        ), None)
        if row is None:
            raise RuntimeError("Hội thoại không còn trong danh sách Tất cả đang tải; sẽ thử lại sau.")
        await _open_seller_conversation(page, row)
        history = await _loaded_seller_history(page, row)
        for start in range(0, len(history), 100):
            status, detail = await asyncio.to_thread(
                post_history_batch, "tiktok", BACKEND_URL, CONNECTOR_TOKEN, history[start:start + 100]
            )
            if not 200 <= status < 300:
                raise RuntimeError(f"CRM từ chối lô lịch sử TikTok (HTTP {status}): {detail[:160]}")
        checkpoint = mark_history_thread_complete(HISTORY_CHECKPOINT, checkpoint, thread_id)
        completed.add(thread_id)
        print(f"✅ Đã kiểm tra {row.get('displayName') or thread_id}: {len(history)} tin đang tải; CRM tự bỏ tin trùng.", flush=True)


def _track_seller_conversation_changes(rows: list[dict], seen: dict, *, baseline: bool = False) -> list[dict]:
    changed = []
    for row in rows:
        key = row["key"]
        current = (row["activity"], int(row["unread"]))
        previous = seen.get(key)
        if baseline:
            seen[key] = current
        elif previous is None:
            if current[1] > 0:
                changed.append(row)
            else:
                seen[key] = current
        elif current != previous:
            if current[1] > 0 or current[0] != previous[0]:
                changed.append(row)
            else:
                seen[key] = current
    return changed


async def _open_seller_conversation(page, row: dict) -> None:
    global CAPTURE_PROBE_UNTIL, CAPTURE_PROBE_REMAINING
    row_id = str(row.get("id") or "")
    row_prefix = "chat-room-conversation-list-item-"
    if not row_id.startswith(row_prefix) or not row_id[len(row_prefix):].isdigit():
        raise RuntimeError("Không xác định được dòng hội thoại Seller Center.")
    card = page.locator(f"#{row_id}")
    current = await card.evaluate(
        r"""row => {
          const username = row.querySelector('[data-testid="chat.chatroom.conversation_card_username"]')?.innerText?.trim() || '';
          const avatar = row.querySelector('img')?.currentSrc || row.querySelector('img')?.getAttribute('src') || '';
          return JSON.stringify([username, avatar]);
        }"""
    )
    if current != row["key"]:
        raise RuntimeError("Danh sách hội thoại vừa thay đổi; bỏ qua lần mở không an toàn.")
    CAPTURE_PROBE_UNTIL = time.monotonic() + 12
    CAPTURE_PROBE_REMAINING = 8
    await card.click(timeout=5000)
    await page.wait_for_selector("#chat-input-send-button", state="visible", timeout=8000)


async def _strict_id_match(page, thread_id: str, recipient_id: str) -> dict | None:
    # Reuse the exact React event-handler contact fields already used by the inbox monitor.
    for row in await _seller_conversation_rows(page):
        if row["threadId"] == thread_id:
            return {
                "rowId": row["id"],
                "recipientMatches": not recipient_id or row["customerId"] == recipient_id,
            }
    return None


async def _send_seller_message(thread_id: str, text: str, recipient_id: str = "") -> dict:
    global CONTROL_PAGE
    if CONTROL_PAGE is None or CONTROL_PAGE.is_closed():
        CONTROL_PAGE = next(
            (page for page in (CONTROL_CONTEXT.pages if CONTROL_CONTEXT else [])
             if not page.is_closed() and _is_seller_chat_url(page.url)),
            None,
        )
    if CONTROL_PAGE is None or CONTROL_PAGE.is_closed():
        raise RuntimeError("Edge TikTok Shop Seller Center chưa sẵn sàng.")
    thread_id, text, recipient_id = str(thread_id or "").strip(), str(text or "").strip(), str(recipient_id or "").strip()
    if not thread_id or not text:
        raise ValueError("Thiếu threadId hoặc nội dung tin nhắn.")
    if len(text) > 2000:
        raise ValueError("Tin nhắn TikTok Shop vượt quá 2.000 ký tự.")
    row = await _strict_id_match(CONTROL_PAGE, thread_id, recipient_id)
    if not row:
        raise RuntimeError("Không tìm thấy đúng hội thoại đã đồng bộ trong Seller Center; mở hội thoại đó trong Edge rồi thử lại.")
    if not row.get("recipientMatches"):
        raise RuntimeError("Mã khách không khớp hội thoại Seller Center; đã hủy gửi để tránh nhầm khách.")
    item = CONTROL_PAGE.locator(f"#{row['rowId']}")
    before = await CONTROL_PAGE.get_by_text(text, exact=True).count()
    await item.click()
    await CONTROL_PAGE.wait_for_timeout(350)

    send_button = CONTROL_PAGE.locator("#chat-input-send-button")
    if await send_button.count() != 1 or not await send_button.is_visible() or await send_button.is_disabled():
        raise RuntimeError("Không tìm thấy nút gửi đang hoạt động trong Seller Center.")
    # Narrow to the editor sharing a parent work area with TikTok's send button.
    editor_index = await CONTROL_PAGE.evaluate(
        r"""() => {
          const send = document.querySelector('#chat-input-send-button');
          if (!send) return -1;
          for (let node = send.parentElement, depth = 0; node && depth < 8; node = node.parentElement, depth++) {
            const editors = [...node.querySelectorAll('[contenteditable="true"],textarea')]
              .filter(el => el.getClientRects().length && !el.disabled && !el.readOnly);
            if (editors.length === 1) return [...document.querySelectorAll('[contenteditable="true"]:not([disabled]), textarea:not([disabled])')].indexOf(editors[0]);
          }
          return -1;
        }"""
    )
    if editor_index < 0:
        raise RuntimeError("Không tìm thấy ô nhập tin nhắn trong Seller Center.")
    all_editors = CONTROL_PAGE.locator("[contenteditable='true']:not([disabled]), textarea:not([disabled])")
    composer = all_editors.nth(editor_index)
    await composer.fill(text)
    await send_button.click()
    try:
        await CONTROL_PAGE.wait_for_function(
            "() => { const e=document.querySelector('[contenteditable=\"true\"],textarea'); return !e || !String(e.value ?? e.innerText ?? '').trim(); }",
            timeout=10000,
        )
        await CONTROL_PAGE.wait_for_function(
            "({text,before}) => [...document.querySelectorAll('body *')].filter(e => e.childElementCount === 0 && e.textContent.trim() === text).length > before",
            arg={"text": text, "before": before}, timeout=10000,
        )
    except Exception as exc:
        raise TikTokDeliveryUnknown(
            "Seller Center chưa xác nhận tin đã gửi; hãy kiểm tra hội thoại trước khi thử lại."
        ) from exc
    RECENT_OUTBOUND[(thread_id, text)] = time.monotonic()
    return {"status": "sent", "message_id": f"tiktok-seller-ui:{thread_id}:{time.time_ns()}", "threadId": thread_id}


def _is_seller_chat_url(value: str) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme == "https" and parsed.hostname == "seller-vn.tiktok.com" and parsed.path.startswith("/chat/inbox/")


class _TikTokControlHandler(BaseHTTPRequestHandler):
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
            self._reply(404, {"detail": "TikTok Seller Center bridge route not found"})
            return
        provided = self.headers.get("X-TikTok-Bridge-Secret", "")
        if not CONTROL_SECRET or not hmac.compare_digest(str(provided), str(CONTROL_SECRET)):
            self._reply(401, {"detail": "TikTok bridge secret không đúng"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 65536:
                raise ValueError("Payload TikTok Shop không hợp lệ.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Payload TikTok Shop không hợp lệ.")
            if CONTROL_LOOP is None:
                self._reply(503, {"detail": "TikTok Seller Center connector chưa sẵn sàng."})
                return
            with CONTROL_SEND_LOCK:
                future = asyncio.run_coroutine_threadsafe(
                    _send_seller_message(payload.get("threadId"), payload.get("message"), payload.get("recipientId")),
                    CONTROL_LOOP,
                )
                result = await_bridge_result(future)
            self._reply(200, result)
        except TikTokDeliveryUnknown as exc:
            self._reply(409, {"code": "delivery_unknown", "detail": str(exc)})
        except ValueError as exc:
            self._reply(400, {"detail": str(exc)})
        except Exception as exc:
            print(f"❌ TikTok Seller Center outbound: {type(exc).__name__}: {exc}", flush=True)
            self._reply(502, {"detail": str(exc)[:300] or "Không thể gửi tin TikTok Shop."})


def _start_control_server(page) -> None:
    global CONTROL_SERVER, CONTROL_LOOP, CONTROL_PAGE, CONTROL_CONTEXT
    CONTROL_LOOP = asyncio.get_running_loop()
    CONTROL_PAGE = page
    CONTROL_CONTEXT = page.context
    if CONTROL_SERVER is not None:
        return
    host = os.getenv("TIKTOK_BRIDGE_CONTROL_HOST", "0.0.0.0")
    try:
        CONTROL_SERVER = ThreadingHTTPServer((host, CONTROL_PORT), _TikTokControlHandler)
        CONTROL_SERVER.daemon_threads = True
        Thread(target=CONTROL_SERVER.serve_forever, daemon=True).start()
        print(f"TikTok Shop outbound bridge: http://{host}:{CONTROL_PORT}/send", flush=True)
    except OSError as exc:
        print(f"⚠️ Không mở được TikTok outbound bridge: {type(exc).__name__}: {exc}", flush=True)


def _handle_page_events(page) -> None:
    loop = asyncio.get_running_loop()

    def schedule(payload, source: str) -> None:
        asyncio.run_coroutine_threadsafe(_inspect_payload(payload, source=source), loop)

    def on_websocket(websocket) -> None:
        source = f"WebSocket {urlparse(websocket.url).path}"
        websocket.on("framereceived", lambda frame: schedule(frame.get("payload") if isinstance(frame, dict) else frame, source))

    async def on_response(response) -> None:
        try:
            parsed = urlparse(response.url)
            if parsed.scheme != "https" or "tiktok" not in (parsed.hostname or ""):
                return
            if "application/json" not in str(response.headers.get("content-type", "")).lower():
                return
            # HTTP chat responses may include a page of old history. Only relay
            # messages created after this connector started to avoid replaying
            # old customer questions into the chatbot queue.
            await _inspect_payload(await response.json(), recent_only=True, source=parsed.path)
        except Exception:
            return

    page.on("websocket", on_websocket)
    page.on("response", lambda response: asyncio.create_task(on_response(response)))


async def run() -> None:
    global BACKEND_URL, CONNECTOR_TOKEN, CONTROL_SECRET, CONTROL_PAGE, CONTROL_CONTEXT, CONNECTOR_STARTED_AT, HISTORY_CHECKPOINT
    print("SmartMerchantTikTok build: TikTok Shop Seller Center inbox bridge", flush=True)
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise SystemExit("Thiếu Playwright. Chạy: python -m pip install playwright") from exc
    BACKEND_URL, CONNECTOR_TOKEN = configure_local_connector("tiktok", RUNTIME, PACKAGE_DIR)
    HISTORY_CHECKPOINT = history_checkpoint_path(RUNTIME, "tiktok", CONNECTOR_TOKEN)
    CONTROL_SECRET = CONNECTOR_TOKEN
    CONNECTOR_STARTED_AT = time.time()
    next_history_scan_at = 0.0
    async with async_playwright() as playwright:
        while True:
            try:
                await asyncio.to_thread(_ensure_edge)
                browser = await playwright.chromium.connect_over_cdp(CDP)
                if not browser.contexts:
                    raise RuntimeError("Edge chưa có browser context.")
                context = browser.contexts[0]
                page = next((item for item in context.pages if _is_seller_chat_url(item.url)), None)
                if page is None:
                    page = await context.new_page()
                    _handle_page_events(page)
                    await page.goto(_seller_inbox_url(), wait_until="domcontentloaded", timeout=120000)
                else:
                    _handle_page_events(page)
                    try:
                        await page.goto(_seller_inbox_url(), wait_until="domcontentloaded", timeout=120000)
                    except Exception:
                        pass
                _start_control_server(page)
                print("TikTok Shop bridge đang theo dõi Seller Center. Đăng nhập thủ công trong Edge nếu được yêu cầu; Ctrl+C để dừng.", flush=True)
                if not _is_seller_chat_url(page.url):
                    print("⚠️ Trang Seller Center chưa ở Hộp thư đến (/chat/inbox/); bridge chưa đọc được hội thoại.", flush=True)
                else:
                    print("✅ Đang ở trang Hộp thư đến của TikTok Shop Seller Center.", flush=True)
                observed_conversations = {}
                conversation_baseline_ready = False
                all_inbox_selected = False
                last_conversation_watch_error = 0.0
                while _cdp_browser_ready() and not page.is_closed():
                    if not _is_seller_chat_url(page.url):
                        print("⚠️ Seller Center đang ở ngoài Hộp thư đến; mở đúng mục Chat để bridge tiếp tục.", flush=True)
                        await asyncio.sleep(5)
                        continue
                    try:
                        rows = await _select_all_seller_conversations(page) if not all_inbox_selected else await _seller_conversation_rows(page)
                        all_inbox_selected = True
                        await _sync_seller_profiles(rows)
                        if rows and not conversation_baseline_ready:
                            _track_seller_conversation_changes(rows, observed_conversations, baseline=True)
                            conversation_baseline_ready = True
                            print(f"✅ Đang theo dõi {len(rows)} hội thoại Seller Center để tự đồng bộ tin mới.", flush=True)
                        if rows and conversation_baseline_ready and time.monotonic() >= next_history_scan_at:
                            try:
                                await _sync_initial_seller_history(page, rows)
                                next_history_scan_at = time.monotonic() + 60
                            except Exception as history_error:
                                next_history_scan_at = time.monotonic() + 60
                                print(f"⚠️ Đồng bộ hội thoại đang tải chưa xong; bridge sẽ tự thử lại sau 1 phút: {type(history_error).__name__}: {str(history_error)[:180]}", flush=True)
                        if conversation_baseline_ready:
                            changed = _track_seller_conversation_changes(rows, observed_conversations)
                            if changed:
                                row = changed[0]
                                previous = observed_conversations.get(row["key"])
                                try:
                                    await _open_seller_conversation(page, row)
                                    observed_conversations[row["key"]] = (row["activity"], int(row["unread"]))
                                    print("🔔 Có hoạt động chat mới; đã mở đúng khung hội thoại, đang đọc tin để chuyển vào CRM.", flush=True)
                                    candidates = await _seller_visible_messages(page, row)
                                    fresh_count = 0
                                    for candidate in candidates:
                                        message = normalize_seller_message(candidate)
                                        if message and _message_is_fresh(message, CONNECTOR_STARTED_AT):
                                            fresh_count += 1
                                            await _deliver(message)
                                    if not fresh_count:
                                        print("ℹ️ Hội thoại đã mở nhưng chưa thấy tin nhắn văn bản mới của khách để đồng bộ.", flush=True)
                                except Exception as exc:
                                    if previous is None:
                                        observed_conversations.pop(row["key"], None)
                                    else:
                                        observed_conversations[row["key"]] = previous
                                    if time.monotonic() - last_conversation_watch_error > 30:
                                        print(f"⚠️ Chưa tự mở được hội thoại mới: {type(exc).__name__}.", flush=True)
                                        last_conversation_watch_error = time.monotonic()
                    except Exception as exc:
                        if time.monotonic() - last_conversation_watch_error > 30:
                            print(f"⚠️ Chưa đọc được danh sách hội thoại Seller Center: {type(exc).__name__}: {str(exc)[:180]}", flush=True)
                            last_conversation_watch_error = time.monotonic()
                    await asyncio.sleep(2)
                print("⚠️ Edge Seller Center bị ngắt; đang thử nối lại.", flush=True)
                report_connector_status("tiktok", BACKEND_URL, CONNECTOR_TOKEN, state="error", error_code="edge_disconnected")
            except Exception as exc:
                print(f"⚠️ TikTok Seller Center connector chưa nối lại được Edge: {type(exc).__name__}: {exc}", flush=True)
                report_connector_status("tiktok", BACKEND_URL, CONNECTOR_TOKEN, state="error", error_code="edge_reconnect_failed")
                await asyncio.sleep(10)
            finally:
                CONTROL_PAGE = None
                CONTROL_CONTEXT = None


def self_test() -> None:
    import tkinter
    from tkinter import ttk
    from playwright.async_api import async_playwright

    if async_playwright is None or ttk is None:
        raise SystemExit("Thiếu runtime chạy TikTok Seller Center.")
    driver = Path(__import__("playwright").__file__).parent / "driver" / "node.exe"
    if not driver.is_file():
        raise SystemExit("Thiếu runtime Playwright trong ứng dụng.")
    _seller_inbox_url()
    print("Smart Merchant TikTok Shop: ứng dụng và runtime đã sẵn sàng.")


if __name__ == "__main__" and "--self-test" in sys.argv:
    self_test()
elif __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("Đã dừng TikTok Shop Seller Center connector.", flush=True)
    except Exception as exc:
        report_connector_status("tiktok", BACKEND_URL, CONNECTOR_TOKEN, state="error", error_code=type(exc).__name__.lower())
        raise
