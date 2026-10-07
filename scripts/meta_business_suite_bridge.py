"""Import Meta Business Suite Messenger or Instagram messages through its UI."""

from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread
from urllib.parse import parse_qs, urlencode, urlparse
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
RUNTIME = Path(os.getenv("SMART_MERCHANT_RUNTIME_DIR") or (Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "SmartMerchantMetaBusinessSuite"))
INBOX_ROOT = "https://business.facebook.com/latest/inbox"
CONNECTOR_STARTED_AT = time.time()
CONTROL_PAGE = None
CONTROL_LOOP: asyncio.AbstractEventLoop | None = None
CONTROL_SECRET = ""
CONTROL_SERVER: ThreadingHTTPServer | None = None
CONTROL_SEND_LOCK = Lock()
_META_GENERIC_NAMES = {"giới thiệu", "messenger", "instagram", "instagram direct", "inbox", "hộp thư đến"}
# Bump this when the DOM parser changes so an existing paired shop gets one
# fresh, full history pass instead of reusing an old "complete" checkpoint.
META_HISTORY_PARSER_REVISION = "virtualized-history-timestamp-avatar-v8"


class MetaDeliveryUnknown(RuntimeError):
    """The send action may have reached Meta, but the UI did not confirm it."""


def _control_port(channel_type: str) -> int:
    variable = "META_INSTAGRAM_BRIDGE_CONTROL_PORT" if channel_type == "instagram" else "META_MESSENGER_BRIDGE_CONTROL_PORT"
    default = "8094" if channel_type == "instagram" else "8093"
    return int(os.getenv(variable, default))


def _bridge_control_url(channel_type: str) -> str:
    variable = "META_INSTAGRAM_BRIDGE_CONTROL_URL" if channel_type == "instagram" else "META_MESSENGER_BRIDGE_CONTROL_URL"
    default = "http://127.0.0.1:8094" if channel_type == "instagram" else "http://127.0.0.1:8093"
    return str(os.getenv(variable, default) or "").strip().rstrip("/")


def await_bridge_result(future, timeout: float = 25) -> dict:
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError as exc:
        raise MetaDeliveryUnknown("Meta chưa xác nhận tin đã gửi; hãy kiểm tra hội thoại trước khi thử lại.") from exc


def _usable_meta_name(value: object) -> str:
    name = " ".join(str(value or "").split()).strip()
    return "" if name.casefold() in _META_GENERIC_NAMES else name[:255]


def parse_meta_datetime(value: object, *, now: datetime | None = None) -> str | None:
    """Parse the rendered Business Suite date separator without guessing old dates."""
    text = " ".join(str(value or "").replace("\u202f", " ").split()).strip(" ,")
    if not text:
        return None
    if re.fullmatch(r"\d{10}(?:\d{3})?", text):
        try:
            epoch = int(text) / (1000 if len(text) == 13 else 1)
            return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return parsed.astimezone(timezone.utc).isoformat()
    except ValueError:
        pass

    current = now or datetime.now().astimezone()
    folded = text.casefold()
    time_match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?:\s*([ap])\.?m\.?)?", folded)
    if not time_match:
        return None
    hour, minute = int(time_match.group(1)), int(time_match.group(2))
    if time_match.group(3):
        hour = hour % 12 + (12 if time_match.group(3) == "p" else 0)
    if hour > 23 or minute > 59:
        return None

    date_text = re.sub(r"(?<!\d)\d{1,2}:\d{2}(?:\s*[ap]\.?m\.?)?", "", folded).strip(" ,")
    date = None
    vi = re.search(r"(?:hôm nay|today|yesterday|hôm qua)?\s*(\d{1,2})\s*tháng\s*(\d{1,2})(?:\s*,?\s*(\d{4}))?", date_text)
    if vi:
        day, month = int(vi.group(1)), int(vi.group(2))
        year = int(vi.group(3) or current.year)
        try:
            date = datetime(year, month, day).date()
        except ValueError:
            return None
    else:
        numeric = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", date_text)
        if numeric:
            first, second, year = map(int, numeric.groups())
            if year < 100:
                year += 2000
            # Business Suite locale may render either DD/MM or MM/DD.
            day, month = (first, second) if first > 12 else (second, first) if second > 12 else (first, second)
            try:
                date = datetime(year, month, day).date()
            except ValueError:
                return None
        else:
            english = re.search(r"(\d{1,2})\s+([a-z]{3,9})\s*,?\s*(\d{4})?", date_text)
            if not english:
                month_first = re.search(r"([a-z]{3,9})\s+(\d{1,2}),?\s*(\d{4})?", date_text)
                if month_first:
                    month_name, day, year_text = month_first.groups()
                    month_names = {
                        "jan": 1, "january": 1, "feb": 2, "february": 2,
                        "mar": 3, "march": 3, "apr": 4, "april": 4,
                        "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
                        "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
                        "oct": 10, "october": 10, "nov": 11, "november": 11,
                        "dec": 12, "december": 12,
                    }
                    month = month_names.get(month_name)
                    if month:
                        try:
                            date = datetime(int(year_text or current.year), month, int(day)).date()
                        except ValueError:
                            return None
            if english:
                day, month_name, year_text = english.groups()
                month_names = {
                    "jan": 1, "january": 1, "feb": 2, "february": 2,
                    "mar": 3, "march": 3, "apr": 4, "april": 4,
                    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
                    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
                    "oct": 10, "october": 10, "nov": 11, "november": 11,
                    "dec": 12, "december": 12,
                }
                month = month_names.get(month_name)
                if month:
                    try:
                        date = datetime(int(year_text or current.year), month, int(day)).date()
                    except ValueError:
                        return None
    if date is None:
        if any(word in folded for word in ("yesterday", "hôm qua")):
            date = (current - timedelta(days=1)).date()
        elif any(word in folded for word in ("today", "hôm nay")):
            date = current.date()
        else:
            return None
    local_time = datetime.combine(date, datetime.min.time()).replace(
        hour=hour, minute=minute, tzinfo=current.tzinfo
    )
    return local_time.astimezone(timezone.utc).isoformat()


def normalize_meta_history(
    channel_type: str,
    thread_id: str,
    customer_id: str,
    display_name: str,
    rows: list[dict],
) -> list[dict]:
    normalized = []
    for row in rows:
        message_id = str(row.get("messageId") or "").strip()
        content = " ".join(str(row.get("message") or "").split())[:10000]
        direction = str(row.get("direction") or "").lower()
        if not message_id or not content or direction not in {"inbound", "outbound"}:
            continue
        normalized.append({
            "threadId": thread_id[:255],
            "customerId": customer_id[:255],
            "messageId": message_id[:255],
            "direction": direction,
            "message": content,
            "messageType": "text",
            "displayName": display_name[:255] or None,
            "createdAt": row.get("createdAt"),
            "avatarUrl": str(row.get("avatarUrl") or "")[:2000] or None,
        })
    return normalized


def _message_created_at(row: dict, *, now: datetime | None = None) -> str | None:
    timestamp = str(row.get("timestamp") or "").strip()
    created_at = parse_meta_datetime(timestamp, now=now)
    if created_at:
        return created_at
    date_label = str(row.get("dateLabel") or "").strip()
    if timestamp:
        # Date separators sometimes include their own time; when an individual
        # bubble exposes only a time, keep the separator's date but use the
        # bubble's time instead of copying the separator timestamp.
        date_only = re.sub(r"(?<!\d)\d{1,2}:\d{2}(?:\s*[ap]\.?m\.?)?", "", date_label, flags=re.IGNORECASE).strip(" ,")
        created_at = parse_meta_datetime(f"{date_only} {timestamp}".strip(), now=now)
        if created_at:
            return created_at
    # A date separator belongs to a group of messages, not to every bubble.
    # Do not copy its time to all rows when a bubble has no own timestamp.
    return None


def _meta_inbox_url(channel_type: str, current_url: str = "") -> str:
    route = "messenger" if channel_type == "facebook" else "instagram_direct"
    current = urlparse(current_url)
    values = parse_qs(current.query)
    query = {key: values[key][-1] for key in ("business_id", "asset_id") if values.get(key)}
    return f"{INBOX_ROOT}/{route}?{urlencode(query)}" if query else f"{INBOX_ROOT}/{route}"


def _meta_conversation_url(channel_type: str, current_url: str, thread_id: str) -> str:
    """Address the exact selected_item_id without leaving the channel inbox."""
    parsed = urlparse(_meta_inbox_url(channel_type, current_url))
    values = parse_qs(parsed.query)
    query = {key: items[-1] for key, items in values.items() if items}
    current_values = parse_qs(urlparse(current_url).query)
    for key in ("mailbox_id", "thread_type", "lang"):
        if current_values.get(key):
            query[key] = current_values[key][-1]
    if channel_type == "instagram" and "thread_type" not in query:
        query["thread_type"] = "IG_MESSAGE"
    query["selected_item_id"] = str(thread_id).strip()
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{urlencode(query)}"


def _is_channel_inbox_url(channel_type: str, current_url: str) -> bool:
    if channel_type not in {"facebook", "instagram"}:
        return False
    route = "messenger" if channel_type == "facebook" else "instagram_direct"
    path = urlparse(str(current_url or "")).path.casefold().rstrip("/")
    expected = f"/latest/inbox/{route}"
    return path == expected or path.startswith(f"{expected}/")


def _channel_name(channel_type: str) -> str:
    return "Messenger" if channel_type == "facebook" else "Instagram" if channel_type == "instagram" else "Meta"


def _find_edge() -> Path | None:
    for root in (
        os.getenv("PROGRAMFILES(X86)", ""),
        os.getenv("PROGRAMFILES", ""),
        os.getenv("LOCALAPPDATA", ""),
    ):
        candidate = Path(root) / "Microsoft/Edge/Application/msedge.exe"
        if candidate.is_file():
            return candidate
    return None


def _cdp_ready(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1.5) as response:
            version = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and str(version.get("Browser", "")).startswith("Edg/")
    except Exception:
        return False


def _start_edge(channel_type: str, port: int) -> None:
    edge = _find_edge()
    if edge is None:
        raise RuntimeError("Không tìm thấy Microsoft Edge.")
    profile = RUNTIME / f"edge-{channel_type}"
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            str(edge), "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
            _meta_inbox_url(channel_type),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("Đã mở Edge riêng cho Meta Business Suite. Đăng nhập thủ công nếu được yêu cầu.", flush=True)
    for _ in range(180):
        if _cdp_ready(port):
            return
        time.sleep(0.5)
    raise RuntimeError("Edge Meta Business Suite chưa sẵn sàng sau 90 giây.")


def _inbox_state(page) -> str:
    parsed = urlparse(str(page.url or ""))
    if parsed.hostname not in {"business.facebook.com", "www.business.facebook.com"}:
        return "wrong_site"
    folded_path = parsed.path.casefold()
    if any(piece in folded_path for piece in ("login", "checkpoint", "challenge")):
        return "login"
    if "/latest/inbox/" not in folded_path and folded_path.rstrip("/") != "/latest/inbox":
        return "outside_inbox"
    return "inbox"


async def _conversation_rows(page) -> list[dict]:
    return await page.evaluate(
        r"""() => {
          const vw = innerWidth, vh = innerHeight;
          const scrollable = [...document.querySelectorAll('*')].filter(e => {
            const r = e.getBoundingClientRect();
            return e.scrollHeight > e.clientHeight + 30 && r.x < vw * 0.38 && r.width > vw * 0.14
              && r.width < vw * 0.4 && r.y > 80 && r.height > vh * 0.3;
          }).sort((a, b) => b.clientHeight - a.clientHeight)[0];
          if (!scrollable) return [];
          const box = scrollable.getBoundingClientRect();
          const assetUrl = node => {
            const style = getComputedStyle(node);
            const srcset = (node.getAttribute?.('srcset') || '').split(',')
              .map(part => {
                const [url, size] = part.trim().split(/\s+/, 2);
                const match = String(size || '').match(/^(\d+(?:\.\d+)?)(w|x)$/);
                return {url, size: match ? Number(match[1]) : 0};
              }).filter(item => item.url).sort((a, b) => b.size - a.size);
            const before = getComputedStyle(node, '::before');
            const after = getComputedStyle(node, '::after');
            const styled = [
              style.backgroundImage, style.maskImage, style.webkitMaskImage,
              before.backgroundImage, before.maskImage, before.webkitMaskImage,
              after.backgroundImage, after.maskImage, after.webkitMaskImage,
            ]
              .filter(value => value && value !== 'none').join(' ');
            const styleUrls = [...styled.matchAll(/url\((?:"([^"]+)"|'([^']+)'|([^)]*))\)/gi)]
              .map(match => match[1] || match[2] || match[3] || '');
            const rawCandidates = [
              node.currentSrc, node.src, node.getAttribute?.('src'),
              node.getAttribute?.('href'), node.getAttribute?.('xlink:href'),
              node.getAttribute?.('data-src'), node.getAttribute?.('data-lazy-src'),
              ...srcset.map(item => item.url), ...styleUrls,
            ];
            for (const candidate of rawCandidates) {
              const raw = String(candidate || '').trim();
              if (!raw || raw.startsWith('data:') || raw.startsWith('blob:')) continue;
              try {
                const url = new URL(raw, location.href);
                if (url.protocol === 'http:' || url.protocol === 'https:') return url.href;
              } catch {}
            }
            return '';
          };
          const avatarFor = (row, rowRect, listBox) => {
            // Meta sometimes mounts the profile photo in a sibling next to the
            // clickable presentation row. Search the immediate wrapper too,
            // then use row geometry so we never borrow a neighbor's avatar.
            const roots = [row, row.parentElement].filter(Boolean);
            const nodes = [...new Set(roots.flatMap(root => [...root.querySelectorAll(
              'img,svg image,[role="img"],[data-testid*="avatar" i],[aria-label*="profile" i],[aria-label*="ảnh đại diện" i],[style*="background" i],[style*="mask" i],*'
            )]))];
            const candidates = nodes.map(node => {
              const r = node.getBoundingClientRect();
              if (r.width < 16 || r.width > 128 || r.height < 16 || r.height > 128
                || r.x < rowRect.x - 2 || r.x >= Math.min(rowRect.x + 110, listBox.x + 110)
                || r.y < rowRect.y - 4 || r.bottom > rowRect.bottom + 4
                || Math.abs((r.y + r.height / 2) - (rowRect.y + rowRect.height / 2)) >= rowRect.height * .42) return null;
              const url = assetUrl(node);
              if (!url.startsWith('http')) return null;
              const alt = node.alt || node.getAttribute('aria-label') || '';
              const hostScore = /(?:cdninstagram|fbcdn|lookaside|scontent)/i.test(url) ? 3 : 0;
              const labelScore = /profile|avatar|ảnh đại diện/i.test(alt) ? 2 : 0;
              return {url, alt, r, score: hostScore + labelScore};
            }).filter(Boolean)
              .sort((a, b) => b.score - a.score || (a.r.x - b.r.x)
                || Math.abs(a.r.y - rowRect.y) - Math.abs(b.r.y - rowRect.y));
            return candidates[0] || null;
          };
          return [...document.querySelectorAll('[role="presentation"]')].map((e, index) => {
            const r = e.getBoundingClientRect();
            const text = (e.innerText || '').trim();
            const lines = text.split(/\n+/).map(line => line.trim()).filter(Boolean);
            const ignored = new Set(['giới thiệu','messenger','instagram','instagram direct','inbox','hộp thư đến','facebook']);
            const avatar = avatarFor(e, r, box);
            const altName = (avatar?.alt || '').replace(/^(?:profile picture|profile photo|ảnh đại diện)\s+(?:of|của)\s*/i, '')
              .replace(/(?:'s)?\s*(?:profile picture|profile photo|ảnh đại diện)$/i, '').trim();
            const displayName = [altName, lines[0] || ''].find(value => value && !ignored.has(value.toLocaleLowerCase())) || '';
            return {e, index, r, text, displayName, avatarUrl: avatar?.url || ''};
          }).filter(x => x.text.length > 4 && x.r.width > box.width * 0.8
            && x.r.height >= 55 && x.r.height <= 180
            && x.r.x >= box.x - 4 && x.r.x < box.x + box.width * 0.1
            && x.r.y >= box.y - 3 && x.r.y < box.bottom
            && getComputedStyle(x.e).cursor === 'pointer')
          .map(x => ({index: x.index, label: x.text.slice(0, 1000), displayName: x.displayName.slice(0, 255), avatarUrl: x.avatarUrl}));
        }"""
    )


async def _open_meta_conversation(page, row: dict, channel_type: str = "") -> str:
    channel_name = _channel_name(channel_type)
    label = str(row.get("label") or "")
    previous_id = await _active_thread_id(page)
    clicked = await page.evaluate(
        r"""(label) => {
          const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
          const expected = normalize(label);
          const vw = innerWidth, vh = innerHeight;
          const list = [...document.querySelectorAll('*')].filter(e => {
            const r = e.getBoundingClientRect();
            return e.scrollHeight > e.clientHeight + 30 && r.x < vw * .38
              && r.width > vw * .14 && r.width < vw * .4 && r.y > 80 && r.height > vh * .3;
          }).sort((a, b) => b.clientHeight - a.clientHeight)[0];
          if (!list || !expected) return false;
          const box = list.getBoundingClientRect();
          const candidates = [...document.querySelectorAll('[role="presentation"]')]
            .filter(e => {
              const r = e.getBoundingClientRect();
              const text = normalize(e.innerText);
              const matches = text === expected || (expected.length === 1000 && text.startsWith(expected));
              return matches && r.width > box.width * .8 && r.height >= 55 && r.height <= 180
                && r.x >= box.x - 4 && r.x < box.x + box.width * .1
                && r.y >= box.y - 3 && r.y < box.bottom
                && getComputedStyle(e).cursor === 'pointer';
            })
            .sort((a, b) => a.getBoundingClientRect().height - b.getBoundingClientRect().height);
          const target = candidates[0];
          if (!target) return false;
          target.click();
          return true;
        }""",
        label,
    )
    if not clicked:
        raise RuntimeError("Không còn tìm thấy đúng dòng hội thoại Meta trong danh sách.")

    expected_name = " ".join(label.splitlines()[0].split()).casefold()
    for _ in range(20):
        await page.wait_for_timeout(250)
        thread_id = await _active_thread_id(page)
        if not thread_id:
            continue
        if thread_id != previous_id:
            return thread_id
        active_name = " ".join((await _active_display_name(page, "")).split()).casefold()
        if active_name and active_name == expected_name:
            return thread_id
        raise RuntimeError(f"{channel_name} chưa xác nhận đã mở đúng hội thoại; chưa nhập lịch sử.")


async def _scroll_meta_list(page) -> dict | None:
    return await page.evaluate(
        r"""() => {
          const vw = innerWidth, vh = innerHeight;
          const el = [...document.querySelectorAll('*')].filter(e => {
            const r = e.getBoundingClientRect();
            return e.scrollHeight > e.clientHeight + 30 && r.x < vw * 0.38 && r.width > vw * 0.14
              && r.width < vw * 0.4 && r.y > 80 && r.height > vh * 0.3;
          }).sort((a, b) => b.clientHeight - a.clientHeight)[0];
          if (!el) return null;
          el.scrollTop = Math.min(el.scrollHeight, el.scrollTop + Math.max(220, Math.floor(el.clientHeight * 0.72)));
          return {top: el.scrollTop, height: el.scrollHeight, client: el.clientHeight};
        }"""
    )


async def _scroll_thread_to_oldest(page) -> None:
    stable_at_top = 0
    prior_count = -1
    for _ in range(45):
        state = await page.evaluate(
            r"""() => {
              const vw = innerWidth, vh = innerHeight;
              const markers = [...document.querySelectorAll('[data-message-id]')].filter(e => {
                const r = e.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && r.x > vw * .16 && r.x < vw * .9;
              });
              const candidates = [];
              for (const marker of markers) {
                let node = marker.parentElement, depth = 0;
                while (node && node !== document.body && depth < 12) {
                  const r = node.getBoundingClientRect();
                  if (r.width > vw * .18 && r.height > vh * .25 && r.x > vw * .14 && r.x < vw * .9) {
                    candidates.push({node, depth});
                  }
                  node = node.parentElement;
                  depth++;
                }
              }
              const unique = [...new Map(candidates.map(x => [x.node, x])).values()];
              unique.sort((a, b) => {
                const aScroll = a.node.scrollHeight > a.node.clientHeight + 10;
                const bScroll = b.node.scrollHeight > b.node.clientHeight + 10;
                return Number(bScroll) - Number(aScroll) || a.depth - b.depth;
              });
              const region = unique[0]?.node;
              if (!region) return null;
              const scrollable = region.scrollHeight > region.clientHeight + 10;
              const top = region.scrollTop;
              if (scrollable) region.scrollTop = 0;
              return {top, count: region.querySelectorAll('[data-message-id]').length, scrollable};
            }"""
        )
        if state is None:
            raise RuntimeError("Meta Business Suite chưa hiển thị vùng tin nhắn; hãy mở đúng hội thoại.")
        if not state["scrollable"]:
            if state["count"]:
                return
            raise RuntimeError("Meta chưa hiển thị tin nhắn trong hội thoại đang mở.")
        await page.wait_for_timeout(400)
        after = await page.evaluate(
            r"""() => {
              const vw = innerWidth, vh = innerHeight;
              const markers = [...document.querySelectorAll('[data-message-id]')].filter(e => {
                const r = e.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && r.x > vw * .16 && r.x < vw * .9;
              });
              for (const marker of markers) {
                let node = marker.parentElement, depth = 0;
                while (node && node !== document.body && depth < 12) {
                  const r = node.getBoundingClientRect();
                  if (r.width > vw * .18 && r.height > vh * .25 && r.x > vw * .14 && r.x < vw * .9
                    && node.scrollHeight > node.clientHeight + 10) {
                    return {top: node.scrollTop, count: node.querySelectorAll('[data-message-id]').length};
                  }
                  node = node.parentElement;
                  depth++;
                }
              }
              return null;
            }"""
        )
        if after is None:
            raise RuntimeError("Vùng tin nhắn Meta biến mất khi tải lịch sử.")
        if after["top"] <= 1 and after["count"] == prior_count:
            stable_at_top += 1
        else:
            stable_at_top = 0
        if after["top"] <= 1 and after["count"] > state["count"]:
            stable_at_top = 0
        if stable_at_top >= 3:
            return
        prior_count = after["count"]
    raise RuntimeError("Không thể xác nhận đã tải lịch sử chat cũ nhất trong Meta Business Suite.")


async def _active_thread_id(page) -> str:
    try:
        return str(parse_qs(urlparse(page.url).query).get("selected_item_id", [""])[-1]).strip()
    except Exception:
        return ""


async def _active_display_name(page, fallback: str) -> str:
    return await page.evaluate(
        r"""(fallback) => {
          const vw = innerWidth;
          const ignored = new Set(['giới thiệu','messenger','instagram','instagram direct','inbox','hộp thư đến']);
          const candidates = [...document.querySelectorAll('[role="heading"],h1,h2,h3,h4')]
            .map(e => ({e, r: e.getBoundingClientRect(), text: (e.innerText || '').trim()}))
            .filter(x => x.text && !ignored.has(x.text.toLocaleLowerCase()) && x.r.width && x.r.x > vw * 0.24 && x.r.x < vw * 0.85 && x.r.y > 80 && x.r.y < 310)
            .sort((a, b) => a.r.y - b.r.y);
          return candidates[0]?.text.slice(0, 255) || fallback || '';
        }""",
        fallback,
    )


async def _active_avatar_url(page, display_name: str = "") -> str:
    return await page.evaluate(
        r"""(displayName) => {
          const normalize = value => (value || '').replace(/\s+/g, ' ').trim().toLocaleLowerCase();
          const wanted = normalize(displayName);
          const vw = innerWidth, vh = innerHeight;
          const assetUrl = node => {
            const style = getComputedStyle(node);
            const srcset = (node.getAttribute?.('srcset') || '').split(',')
              .map(part => {
                const [url, size] = part.trim().split(/\s+/, 2);
                const match = String(size || '').match(/^(\d+(?:\.\d+)?)(w|x)$/);
                return {url, size: match ? Number(match[1]) : 0};
              }).filter(item => item.url).sort((a, b) => b.size - a.size);
            const before = getComputedStyle(node, '::before');
            const after = getComputedStyle(node, '::after');
            const styled = [
              style.backgroundImage, style.maskImage, style.webkitMaskImage,
              before.backgroundImage, before.maskImage, before.webkitMaskImage,
              after.backgroundImage, after.maskImage, after.webkitMaskImage,
            ]
              .filter(value => value && value !== 'none').join(' ');
            const styleUrls = [...styled.matchAll(/url\((?:"([^"]+)"|'([^']+)'|([^)]*))\)/gi)]
              .map(match => match[1] || match[2] || match[3] || '');
            const rawCandidates = [
              node.currentSrc, node.src, node.getAttribute?.('src'),
              node.getAttribute?.('href'), node.getAttribute?.('xlink:href'),
              node.getAttribute?.('data-src'), node.getAttribute?.('data-lazy-src'),
              ...srcset.map(item => item.url), ...styleUrls,
            ];
            for (const candidate of rawCandidates) {
              const raw = String(candidate || '').trim();
              if (!raw || raw.startsWith('data:') || raw.startsWith('blob:')) continue;
              try {
                const url = new URL(raw, location.href);
                if (url.protocol === 'http:' || url.protocol === 'https:') return url.href;
              } catch {}
            }
            return '';
          };
          const headings = [...document.querySelectorAll('[role="heading"],h1,h2,h3,h4')]
            .filter(node => normalize(node.innerText) === wanted)
            .map(node => ({node, r: node.getBoundingClientRect()}))
            .filter(item => item.r.width && item.r.x > vw * .22 && item.r.x < vw * .83
              && item.r.y > 25 && item.r.y < Math.min(vh * .35, 280))
            .sort((a, b) => a.r.y - b.r.y);
          for (const heading of headings) {
            let ancestor = heading.node;
            for (let depth = 0; ancestor && ancestor !== document.body && depth < 7; depth++, ancestor = ancestor.parentElement) {
              const hr = heading.r;
              const roots = [ancestor, ancestor.parentElement].filter(Boolean);
              const nodes = [...new Set(roots.flatMap(root => [...root.querySelectorAll(
                'img,svg image,[role="img"],[data-testid*="avatar" i],[aria-label*="profile" i],[aria-label*="ảnh đại diện" i],[style*="background" i],[style*="mask" i],*'
              )]))];
              const candidates = nodes.map(node => {
                const r = node.getBoundingClientRect();
                if (r.width < 16 || r.width > 160 || r.height < 16 || r.height > 160
                  || r.x >= hr.x || hr.x - r.right >= 100
                  || Math.abs((r.y + r.height/2) - (hr.y + hr.height/2)) >= 60) return null;
                const url = assetUrl(node);
                if (!url.startsWith('http')) return null;
                const alt = node.alt || node.getAttribute('aria-label') || '';
                const hostScore = /(?:cdninstagram|fbcdn|lookaside|scontent)/i.test(url) ? 3 : 0;
                const labelScore = /profile|avatar|ảnh đại diện/i.test(alt) ? 2 : 0;
                return {url, r, score: hostScore + labelScore};
              }).filter(Boolean)
                .sort((a, b) => b.score - a.score || (hr.x - a.r.right) - (hr.x - b.r.right));
              if (candidates.length) return candidates[0].url;
            }
          }
          // Instagram often renders the profile image in a sibling header node
          // instead of inside the heading ancestor. Keep a conservative header
          // fallback so we do not accidentally pick a message attachment.
          const fallback = [...document.querySelectorAll('img,svg image,[role="img"],[data-testid*="avatar" i],[aria-label*="profile" i],[aria-label*="ảnh đại diện" i],[style*="background" i],[style*="mask" i],*')]
            .map(node => {
              const r = node.getBoundingClientRect();
              if (r.width < 16 || r.width > 160 || r.height < 16 || r.height > 160
                || r.x <= vw * .18 || r.x >= vw * .86 || r.y <= 25 || r.y >= Math.min(vh * .38, 320)) return null;
              const url = assetUrl(node);
              return url ? {url, r, alt: node.alt || node.getAttribute('aria-label') || ''} : null;
            })
            .filter(Boolean)
            .sort((a, b) => (Number(/profile|avatar|ảnh đại diện/i.test(b.alt)) - Number(/profile|avatar|ảnh đại diện/i.test(a.alt)))
              || a.r.y - b.r.y);
          return fallback[0]?.url || '';
        }""",
        display_name,
    )


async def _scroll_thread_page(page, direction: str = "down") -> dict | None:
    """Move the virtualized Meta message pane and report its current bounds."""
    return await page.evaluate(
        r"""(direction) => {
          const vw = innerWidth, vh = innerHeight;
          const markers = [...document.querySelectorAll('[data-message-id]')].filter(e => {
            const r = e.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && r.x > vw * .16 && r.x < vw * .9;
          });
          const candidates = [];
          for (const marker of markers) {
            let node = marker.parentElement, depth = 0;
            while (node && node !== document.body && depth < 12) {
              const r = node.getBoundingClientRect();
              if (r.width > vw * .18 && r.height > vh * .25 && r.x > vw * .14 && r.x < vw * .9
                && node.scrollHeight > node.clientHeight + 10) candidates.push({node, depth});
              node = node.parentElement;
              depth++;
            }
          }
          const region = [...new Map(candidates.map(item => [item.node, item])).values()]
            // Prefer the message pane's long virtualized scroll range over
            // nearby nested panels that scroll only a few hundred pixels.
            .sort((a, b) => (b.node.scrollHeight - b.node.clientHeight)
              - (a.node.scrollHeight - a.node.clientHeight) || a.depth - b.depth)[0]?.node;
          if (!region) return null;
          const before = region.scrollTop;
          const delta = Math.max(260, Math.floor(region.clientHeight * .78));
          if (direction === 'top') region.scrollTop = 0;
          else region.scrollTop = Math.min(region.scrollHeight, before + delta);
          return {top: region.scrollTop, height: region.scrollHeight, client: region.clientHeight,
            count: region.querySelectorAll('[data-message-id]').length, moved: region.scrollTop !== before};
        }""",
        direction,
    )


async def _hover_message_timestamp(page, message_id: str) -> str:
    """Read the timestamp Meta reveals when hovering one message bubble."""
    point = await page.evaluate(
        r"""(messageId) => {
          const vw = innerWidth, vh = innerHeight;
          const markers = [...document.querySelectorAll('[data-message-id]')]
            .filter(node => node.getAttribute('data-message-id') === messageId);
          const marker = markers.find(candidate => {
            const r = candidate.getBoundingClientRect();
            let pane = candidate.parentElement;
            for (let depth = 0; pane && pane !== document.body && depth < 14; depth++, pane = pane.parentElement) {
              const p = pane.getBoundingClientRect();
              if (p.width > vw * .18 && p.height > vh * .25 && p.x > vw * .14 && p.x < vw * .9
                && pane.scrollHeight > pane.clientHeight + 10) {
                return r.width > 0 && r.height > 0 && r.right > p.left && r.left < p.right
                  && r.bottom > p.top && r.top < p.bottom && r.y < vh && r.bottom > 0;
              }
            }
            return false;
          });
          if (!marker) return null;
          let bubble = marker;
          for (let node = marker.parentElement; node && node !== document.body; node = node.parentElement) {
            if (node.querySelectorAll('[data-message-id]').length !== 1) break;
            bubble = node;
          }
          const leaves = [...bubble.querySelectorAll('span,div')]
            .filter(node => node.children.length === 0 && (node.innerText || '').trim())
            .sort((a,b) => (b.innerText || '').trim().length - (a.innerText || '').trim().length);
          const markerRect = marker.getBoundingClientRect();
          const targetRect = leaves.map(node => node.getBoundingClientRect()).find(r => r.width > 0
            && r.height > 0 && r.right > 0 && r.left < vw && r.bottom > 0 && r.top < vh
            && r.right > markerRect.left - 160 && r.left < markerRect.right + 160);
          const targetVisible = targetRect && targetRect.width > 0 && targetRect.height > 0
            && targetRect.right > 0 && targetRect.left < vw && targetRect.bottom > 0 && targetRect.top < vh;
          const r = targetVisible ? targetRect : markerRect;
          return {x: Math.max(2, Math.min(vw - 2, r.left + r.width / 2)),
            y: Math.max(2, Math.min(vh - 2, r.top + r.height / 2))};
        }""",
        message_id,
    )
    if not point:
        return ""
    # Move away first to ensure any prior bubble tooltip is dismissed, then
    # hover this exact visible bubble. This reads UI metadata only; it does not
    # click, open links, or send a message.
    try:
        await page.mouse.move(2, 2)
        await page.wait_for_function(
            r"""() => ![...document.querySelectorAll('[role="tooltip"]')].some(node => {
              const text = (node.innerText || '').replace(/\s+/g, ' ').trim();
              return /^\d{1,2}:\d{2}(?:\s*[ap]\.?m\.?)?(?:\s+\d{1,2}\s+tháng\s+\d{1,2}(?:,?\s*\d{4})?|\s+[a-z]{3,9}\s+\d{1,2},?\s*\d{4})?$/i.test(text)
                || /^\d{4}-\d\d-\d\dT\d\d:\d\d/.test(text);
            })""",
            timeout=1500,
            polling=50,
        )
        await page.mouse.move(point["x"], point["y"])
    except Exception:
        return ""
    try:
        await page.wait_for_function(
            r"""() => [...document.querySelectorAll('[role="tooltip"]')].some(node => {
              const text = (node.innerText || '').replace(/\s+/g, ' ').trim();
              return /^\d{1,2}:\d{2}(?:\s*[ap]\.?m\.?)?(?:\s+\d{1,2}\s+tháng\s+\d{1,2}(?:,?\s*\d{4})?|\s+[a-z]{3,9}\s+\d{1,2},?\s*\d{4})?$/i.test(text)
                || /^\d{4}-\d\d-\d\dT\d\d:\d\d/.test(text);
            })""",
            timeout=1000,
            polling=50,
        )
    except Exception:
        return ""
    values = await page.locator('[role="tooltip"]').all_inner_texts()
    for value in values:
        timestamp = " ".join(str(value or "").split()).strip()
        if parse_meta_datetime(timestamp) or re.fullmatch(r"\d{1,2}:\d{2}(?:\s*[ap]\.?m\.?)?", timestamp, re.IGNORECASE):
            return timestamp
    return ""


async def _collect_meta_history_rows(
    page, channel_type: str, thread_id: str, display_name: str, avatar_url: str,
    *, scroll_oldest: bool,
) -> list[dict]:
    """Collect every virtualized bubble, not just the viewport at the top."""
    if scroll_oldest:
        await _scroll_thread_to_oldest(page)
        await page.wait_for_timeout(350)
    collected: dict[str, dict] = {}
    timestamp_attempts: dict[str, int] = {}
    stable_bottom = 0
    date_context = ""
    for _ in range(140):
        visible = await _visible_message_rows(page, channel_type, thread_id, display_name, avatar_url)
        attempted_this_pass: set[str] = set()
        for row in visible:
            message_id = str(row.get("messageId") or "").strip()
            if not message_id:
                continue
            previous = collected.get(message_id)
            if (not row.get("createdAt") and not (previous and previous.get("createdAt"))
                and message_id not in attempted_this_pass and timestamp_attempts.get(message_id, 0) < 2):
                attempted_this_pass.add(message_id)
                timestamp_attempts[message_id] = timestamp_attempts.get(message_id, 0) + 1
                hover_timestamp = await _hover_message_timestamp(page, message_id)
                if hover_timestamp:
                    row["timestamp"] = hover_timestamp
                    row["createdAt"] = _message_created_at(row)
            if row.get("dateLabel"):
                date_context = str(row.get("dateLabel") or "")
            if row.get("timestamp") and date_context:
                row["createdAt"] = _message_created_at(
                    {"timestamp": row.get("timestamp"), "dateLabel": date_context}
                ) or row.get("createdAt")
            previous = collected.get(message_id)
            if previous is None or row.get("dateLabel") or (not previous.get("createdAt") and row.get("createdAt")):
                collected[message_id] = row
        state = await _scroll_thread_page(page, "down")
        if state is None:
            if collected:
                break
            raise RuntimeError("Meta chưa hiển thị vùng cuộn tin nhắn; không thể đọc lịch sử.")
        at_bottom = state["top"] + state["client"] >= state["height"] - 4
        if at_bottom and not state.get("moved"):
            stable_bottom += 1
        else:
            stable_bottom = 0
        if stable_bottom >= 3:
            break
        await page.wait_for_timeout(260)
    return list(collected.values())


async def _visible_message_rows(page, channel_type: str, thread_id: str, display_name: str, avatar_url: str = "") -> list[dict]:
    raw = await page.evaluate(
        r"""() => {
          const vw = innerWidth, vh = innerHeight;
          const first = [...document.querySelectorAll('[data-message-id]')].find(e => {
            const r = e.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && r.x > vw * .16 && r.x < vw * .9;
          });
          if (!first) return null;
          let region = null, fallbackRegion = null, node = first.parentElement, depth = 0;
          while (node && node !== document.body && depth++ < 14) {
            const r = node.getBoundingClientRect();
            const fitsMessagePane = r.width > vw * .18 && r.height > vh * .25
              && r.x > vw * .14 && r.x < vw * .9;
            if (fitsMessagePane) {
              fallbackRegion ||= node;
              if (node.scrollHeight > node.clientHeight + 10) { region = node; break; }
            }
            node = node.parentElement;
          }
          region ||= fallbackRegion;
          if (!region || region === document.body) return null;
          // Read from the actual scroll viewport. Message rows are nested in a
          // full-height content wrapper, so treating that wrapper as the pane
          // makes off-screen history look visible and breaks lazy pagination.
          const children = [...region.children];
          const rr = region.getBoundingClientRect();
          const dateLabels = [...region.querySelectorAll('span,div')]
            .filter(node => node.children.length === 0)
            .map(node => ({node, text: (node.innerText || '').replace(/\s+/g, ' ').trim()}))
            .filter(item => /^(?:(?:today|yesterday|hôm nay|hôm qua)\s+)?\d{1,2}:\d{2}(?:\s*[ap]\.?m\.?)?\s+\d{1,2}\s+tháng\s+\d{1,2}(?:,?\s*\d{4})?$/i.test(item.text)
              || /^(?:(?:today|yesterday|hôm nay|hôm qua)\s+)?\d{1,2}:\d{2}(?:\s*[ap]\.?m\.?)?\s+[a-z]{3,9}\s+\d{1,2},?\s*\d{4}$/i.test(item.text));
          const dateLabelFor = marker => {
            let label = '';
            for (const item of dateLabels) {
              if (item.node === marker || item.node.contains(marker) || marker.contains(item.node)) continue;
              if (item.node.compareDocumentPosition(marker) & Node.DOCUMENT_POSITION_FOLLOWING) label = item.text;
            }
            return label;
          };
          let dateLabel = '';
          const result = [];
          const timestampFrom = (child, marker) => {
            const values = [];
            const epochValues = [];
            const epochAttrs = new Set(['data-timestamp','data-time','data-created-at','data-create-time','data-sent-at','data-message-time','data-epoch']);
            const add = (value, attribute = '') => {
              const text = String(value || '').replace(/\s+/g, ' ').trim();
              if (text && text.length <= 140) {
                values.push(text);
                if (epochAttrs.has(attribute) && /^\d{10,13}$/.test(text)) epochValues.push(text);
              }
            };
            let node = marker;
            for (let depth = 0; node && node !== child.parentElement && depth < 10; depth++, node = node.parentElement) {
              for (const attr of ['datetime','title','aria-label','data-tooltip-content','data-timestamp','data-time','data-created-at','data-create-time','data-sent-at','data-message-time','data-epoch']) add(node.getAttribute?.(attr), attr);
              if (node === marker) {
                for (const item of child.querySelectorAll('time[datetime],[datetime],[data-testid*="timestamp"],[data-created-at],[data-create-time],[data-sent-at],[data-message-time],[aria-label],[title],[data-tooltip-content]')) {
                  for (const attr of ['datetime','title','aria-label','data-tooltip-content','data-timestamp','data-time','data-created-at','data-create-time','data-sent-at','data-message-time','data-epoch']) add(item.getAttribute?.(attr), attr);
                }
              }
            }
            // Some Instagram layouts render a timestamp as its own short
            // line. Only accept a complete timestamp-shaped line, never a
            // phone number or a time mentioned inside the message body.
            for (const line of (child.innerText || '').split(/\n+/)) add(line);
            const timestamp = epochValues[0] || values.find(value =>
              /^\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:Z|[+-]\d\d:?\d\d)?$/i.test(value) ||
              /^(?:(?:today|yesterday|hôm nay|hôm qua)\s+)?\d{1,2}:\d{2}(?:\s*[ap]\.?m\.?)?(?:\s+(?:\d{1,2}\s+tháng\s+\d{1,2}(?:,?\s*\d{4})?|[a-z]{3,9}\s+\d{1,2},?\s*\d{4}))?$/i.test(value));
            return timestamp || '';
          };
          for (const child of children) {
            const markers = [...child.querySelectorAll('[data-message-id]')];
            if (!markers.length) {
              const label = (child.innerText || '').trim();
              if (label && label.length < 80 && (
                /\d{1,2}:\d{2}/.test(label) ||
                /today|yesterday|hôm nay|hôm qua|\d{1,2}\s+tháng\s+\d{1,2}|\b(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*\b|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b/i.test(label)
              )) dateLabel = label;
              continue;
            }
            for (const marker of markers) {
              const markerRect = marker.getBoundingClientRect();
              if (markerRect.width <= 0 || markerRect.height <= 0 || markerRect.right < rr.left
                || markerRect.left > rr.right || markerRect.bottom < rr.top || markerRect.top > rr.bottom
                || markerRect.bottom < 0 || markerRect.top > vh) continue;
              const id = marker.getAttribute('data-message-id') || '';
              // Some Meta rows group consecutive bubbles into one DOM child.
              // Walk up to the highest ancestor that still owns just this ID,
              // so every bubble is emitted once with its own text and direction.
              let messageNode = marker;
              for (let node = marker.parentElement; node && node !== child.parentElement; node = node.parentElement) {
                if (node.querySelectorAll('[data-message-id]').length !== 1) break;
                messageNode = node;
                if (node === child) break;
              }
              let text = (messageNode.innerText || '').trim();
              if (!id || !text) continue;
              const textNode = [...messageNode.querySelectorAll('span,div')]
                .filter(e => e.children.length === 0 && (e.innerText || '').trim())
                .sort((a, b) => (b.innerText || '').length - (a.innerText || '').length)[0];
              const bubble = (textNode || marker).getBoundingClientRect();
              const incoming = bubble.left + bubble.width / 2 < rr.left + rr.width / 2;
              if (!incoming) text = text.replace(/\s*(?:(?:Đã gửi|Đã xem|Sent|Seen)\s*)?Người gửi\s*:\s*[\s\S]*$/iu, '').trim();
              if (!text) continue;
              const perMessageTimestamp = timestampFrom(messageNode, marker);
              result.push({messageId: id, message: text.slice(0, 10000), direction: incoming ? 'inbound' : 'outbound', timestamp: perMessageTimestamp, dateLabel: dateLabelFor(marker) || dateLabel, bubbleX: Math.round(bubble.left), bubbleY: Math.round(bubble.top)});
            }
          }
          return result;
        }"""
    )
    if not isinstance(raw, list):
        return []
    raw = _dedupe_visible_message_rows(raw)
    return [
        {
            "messageId": str(item.get("messageId") or ""),
            "message": str(item.get("message") or ""),
            "direction": str(item.get("direction") or ""),
            "createdAt": _message_created_at(item),
            "timestamp": str(item.get("timestamp") or ""),
            "dateLabel": str(item.get("dateLabel") or ""),
            "threadId": thread_id,
            "customerId": thread_id,
            "displayName": display_name,
            "avatarUrl": avatar_url,
            "messageType": "text",
        }
        for item in raw
    ]


def _dedupe_visible_message_rows(rows: list[dict]) -> list[dict]:
    """Collapse nested Meta IDs that describe the same rendered bubble."""
    visible = []
    seen = set()
    for item in rows:
        message = " ".join(str(item.get("message") or "").split()).casefold()
        position = (item.get("bubbleX"), item.get("bubbleY"))
        key = (item.get("direction"), message, *position) if message and None not in position else item.get("messageId")
        if key in seen:
            continue
        seen.add(key)
        visible.append(item)
    return visible


async def _send_meta_message(thread_id: object, message: object, recipient_id: object = "") -> dict:
    thread_id = str(thread_id or "").strip()
    message = str(message or "").strip()
    if not thread_id or not message:
        raise ValueError("Thiếu mã hội thoại hoặc nội dung trả lời Meta.")
    page = CONTROL_PAGE
    if page is None or page.is_closed():
        raise RuntimeError("Meta Business Suite connector chưa sẵn sàng; hãy mở Edge đã ghép nối.")
    if not _is_channel_inbox_url(os.getenv("SMART_MERCHANT_CHANNEL_TYPE", ""), page.url):
        raise RuntimeError("Edge không ở đúng hộp thư Meta đã ghép nối; chưa gửi tin.")

    active_id = await _active_thread_id(page)
    if active_id != thread_id:
        await page.goto(_meta_conversation_url(os.getenv("SMART_MERCHANT_CHANNEL_TYPE", ""), page.url, thread_id),
                        wait_until="domcontentloaded", timeout=30000)
        for _ in range(24):
            await page.wait_for_timeout(250)
            if await _active_thread_id(page) == thread_id:
                break
        else:
            raise RuntimeError("Meta không mở được đúng hội thoại để gửi; hãy kiểm tra lại cuộc trò chuyện trong CRM.")
        await page.wait_for_timeout(500)

    target = await page.evaluate(
        r"""() => {
          const vw = innerWidth, vh = innerHeight;
          const visible = node => {
            const r = node.getBoundingClientRect(), s = getComputedStyle(node);
            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
          };
          const editors = [...document.querySelectorAll('textarea,[contenteditable="true"],[role="textbox"],input[type="text"]')]
            .filter(node => {
              if (!visible(node)) return false;
              const r = node.getBoundingClientRect();
              if (r.x < vw * .20 || r.x > vw * .82 || r.y < vh * .52 || r.width < vw * .20) return false;
              const descriptor = [node.getAttribute('aria-label'), node.getAttribute('placeholder'), node.getAttribute('data-placeholder'), node.getAttribute('data-testid')].join(' ').toLocaleLowerCase();
              return !/(search|tìm kiếm|tìm kiếm)/i.test(descriptor);
            }).map(node => {
              const r = node.getBoundingClientRect();
              const descriptor = [node.getAttribute('aria-label'), node.getAttribute('placeholder'), node.getAttribute('data-placeholder'), node.getAttribute('data-testid')].join(' ').toLocaleLowerCase();
              const score = (/message|reply|trả lời|tin nhắn|write/i.test(descriptor) ? 1000 : 0)
                + (node.isContentEditable ? 100 : 0) + r.width - Math.abs(vh - r.bottom);
              return {node, score, r};
            }).sort((a, b) => b.score - a.score);
          const editor = editors[0]?.node;
          if (!editor) return null;
          for (const node of document.querySelectorAll('[data-smart-merchant-meta-composer]')) node.removeAttribute('data-smart-merchant-meta-composer');
          editor.setAttribute('data-smart-merchant-meta-composer', 'active');
          const er = editor.getBoundingClientRect();
          const buttons = [...document.querySelectorAll('button,[role="button"]')].filter(visible).map(node => {
            const r = node.getBoundingClientRect();
            const name = [node.getAttribute('aria-label'), node.getAttribute('title'), node.getAttribute('data-testid'), node.innerText].join(' ').trim();
            return {node, r, name, distance: Math.abs(r.y + r.height / 2 - (er.y + er.height / 2))};
          }).filter(item => item.r.x > vw * .20 && item.r.x < vw * .82 && item.r.y > vh * .50
            && item.distance < 100 && /(send|gửi|tin nhắn)/i.test(item.name))
            .sort((a, b) => a.distance - b.distance);
          const button = buttons[0]?.node;
          if (button) button.setAttribute('data-smart-merchant-meta-send', 'active');
          return {
            hasButton: !!button,
            messageIds: [...new Set([...document.querySelectorAll('[data-message-id]')]
              .map(node => node.getAttribute('data-message-id')).filter(Boolean))]
          };
        }"""
    )
    if not target:
        raise RuntimeError("Không nhận diện được ô trả lời trong hội thoại Meta đang mở.")
    existing_message_ids = set(target.get("messageIds") or [])
    composer = page.locator('[data-smart-merchant-meta-composer="active"]')
    await composer.fill(message)
    send_target = await page.evaluate(
        r"""() => {
          const editor = document.querySelector('[data-smart-merchant-meta-composer="active"]');
          if (!editor) return {hasButton: false};
          const vw = innerWidth, vh = innerHeight, er = editor.getBoundingClientRect();
          const visible = node => {
            const r = node.getBoundingClientRect(), s = getComputedStyle(node);
            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
          };
          for (const node of document.querySelectorAll('[data-smart-merchant-meta-send]')) node.removeAttribute('data-smart-merchant-meta-send');
          const button = [...document.querySelectorAll('button,[role="button"]')]
            .filter(visible).map(node => {
              const r = node.getBoundingClientRect();
              const name = [node.getAttribute('aria-label'), node.getAttribute('title'), node.getAttribute('data-testid'), node.innerText].join(' ').trim();
              return {node, r, name, distance: Math.abs(r.y + r.height / 2 - (er.y + er.height / 2))};
            }).filter(item => item.r.x > vw * .20 && item.r.x < vw * .82 && item.r.y > vh * .50
              && item.distance < 100 && /(send|gửi|tin nhắn)/i.test(item.name))
            .sort((a, b) => a.distance - b.distance)[0]?.node;
          if (button) button.setAttribute('data-smart-merchant-meta-send', 'active');
          return {hasButton: !!button};
        }"""
    )
    button = page.locator('[data-smart-merchant-meta-send="active"]')
    try:
        if send_target and send_target.get("hasButton"):
            await button.click(timeout=5000)
        else:
            await composer.press("Enter")
    except Exception as exc:
        raise MetaDeliveryUnknown("Meta chưa xác nhận thao tác gửi; kiểm tra hội thoại trước khi thử lại để tránh gửi trùng.") from exc

    for _ in range(20):
        await page.wait_for_timeout(250)
        state = await page.evaluate(
            r"""({messageText, existingMessageIds}) => {
              const wanted = (messageText || '').replace(/\s+/g, ' ').trim();
              const previous = new Set(existingMessageIds || []);
              const editor = document.querySelector('[data-smart-merchant-meta-composer="active"]');
              const value = editor ? ('value' in editor ? editor.value : editor.innerText || editor.textContent || '') : '';
              const vw = innerWidth, vh = innerHeight;
              const markers = [...document.querySelectorAll('[data-message-id]')].filter(node => {
                const id = node.getAttribute('data-message-id') || '';
                if (!id || previous.has(id)) return false;
                const r = node.getBoundingClientRect();
                if (!r.width || !r.height || r.x < vw * .2 || r.x > vw * .82 || r.y < vh * .1) return false;
                let container = node;
                for (let i = 0; i < 5 && container.parentElement; i++, container = container.parentElement) {
                  if ((container.innerText || '').includes(messageText)) break;
                }
                const text = (container.innerText || node.innerText || '').replace(/\s+/g, ' ').trim();
                return text.includes(wanted) && r.x + r.width / 2 > vw * .48;
              });
              return {empty: !!editor && !value.trim(), messageId: markers[0]?.getAttribute('data-message-id') || ''};
            }""",
            {"messageText": message, "existingMessageIds": list(existing_message_ids)},
        )
        if state and state.get("messageId"):
            return {
                "status": "sent",
                "message_id": state["messageId"],
                "threadId": thread_id,
            }
    raise MetaDeliveryUnknown("Meta chưa xác nhận tin đã gửi; hãy kiểm tra hội thoại trước khi thử lại.")


class _MetaControlHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args) -> None:
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
            self._reply(404, {"detail": "Meta Business Suite bridge route not found"})
            return
        provided = self.headers.get("X-Meta-Bridge-Secret", "")
        if not CONTROL_SECRET or not hmac.compare_digest(str(provided), str(CONTROL_SECRET)):
            self._reply(401, {"detail": "Meta bridge secret không đúng"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 65536:
                raise ValueError("Payload Meta không hợp lệ.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Payload Meta không hợp lệ.")
            if CONTROL_LOOP is None:
                self._reply(503, {"detail": "Meta Business Suite connector chưa sẵn sàng."})
                return
            with CONTROL_SEND_LOCK:
                future = asyncio.run_coroutine_threadsafe(
                    _send_meta_message(payload.get("threadId"), payload.get("message"), payload.get("recipientId")),
                    CONTROL_LOOP,
                )
                result = await_bridge_result(future)
            self._reply(200, result)
        except MetaDeliveryUnknown as exc:
            self._reply(409, {"code": "delivery_unknown", "detail": str(exc)})
        except ValueError as exc:
            self._reply(400, {"detail": str(exc)})
        except Exception as exc:
            print(f"❌ Meta Business Suite outbound: {type(exc).__name__}: {exc}", flush=True)
            self._reply(502, {"detail": str(exc)[:300] or "Không thể gửi tin Meta."})


def _start_control_server(page, channel_type: str, connector_token: str) -> None:
    global CONTROL_PAGE, CONTROL_LOOP, CONTROL_SECRET, CONTROL_SERVER
    CONTROL_PAGE = page
    CONTROL_LOOP = asyncio.get_running_loop()
    CONTROL_SECRET = connector_token
    if CONTROL_SERVER is not None:
        return
    host = os.getenv("META_BRIDGE_CONTROL_HOST", "0.0.0.0")
    port = _control_port(channel_type)
    try:
        CONTROL_SERVER = ThreadingHTTPServer((host, port), _MetaControlHandler)
        CONTROL_SERVER.daemon_threads = True
        Thread(target=CONTROL_SERVER.serve_forever, daemon=True).start()
        print(f"{_channel_name(channel_type)} outbound bridge: http://{host}:{port}/send", flush=True)
    except OSError as exc:
        print(f"⚠️ Không mở được outbound bridge {_channel_name(channel_type)}: {type(exc).__name__}: {exc}", flush=True)


def _send_history(
    channel_type: str,
    backend_url: str,
    connector_token: str,
    messages: list[dict],
    *,
    live_message_ids: set[str] | None = None,
) -> tuple[int, str]:
    return post_history_batch(
        channel_type,
        backend_url,
        connector_token,
        messages,
        live_message_ids=live_message_ids,
    )


def _post_meta_profiles(
    channel_type: str,
    backend_url: str,
    connector_token: str,
    profiles: list[dict],
) -> tuple[int, str]:
    request = Request(
        f"{backend_url.rstrip('/')}/api/channels/{channel_type}/profiles",
        data=json.dumps({"profiles": profiles}, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Authorization": f"Bearer {connector_token}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:300]
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


async def _scan_instagram_profile_avatars(
    page,
    backend_url: str,
    connector_token: str,
    checkpoint_path: Path,
) -> dict:
    """Backfill Instagram avatars independently of the one-time message history pass."""
    checkpoint = load_history_checkpoint(checkpoint_path)
    if checkpoint.get("complete"):
        return {"complete": True, "scanned": 0, "detected": 0, "updated": 0, "missing": 0}

    seen_positions: set[str] = set()
    profile_ids: set[str] = set()
    detected_ids: set[str] = set()
    updated = 0
    missing = 0
    stable_bottom = 0
    scan_ok = True
    await page.evaluate(
        r"""() => {
          const vw=innerWidth,vh=innerHeight;
          const list=[...document.querySelectorAll('*')].filter(e=>{const r=e.getBoundingClientRect();return e.scrollHeight>e.clientHeight+30&&r.x<vw*.38&&r.width>vw*.14&&r.width<vw*.4&&r.y>80&&r.height>vh*.3}).sort((a,b)=>b.clientHeight-a.clientHeight)[0];
          if(list) list.scrollTop=0;
        }"""
    )
    await page.wait_for_timeout(450)
    print("📷 Đang rà soát avatar Instagram riêng; không quét/nhập lại tin nhắn cũ…", flush=True)

    async def post_batch(batch: list[dict]) -> None:
        nonlocal checkpoint, updated, scan_ok
        status, detail = await asyncio.to_thread(
            _post_meta_profiles, "instagram", backend_url, connector_token, batch
        )
        if not 200 <= status < 300:
            scan_ok = False
            print(f"⚠️ CRM chưa nhận được avatar Instagram (HTTP {status}): {detail[:120]}", flush=True)
            return
        try:
            result = json.loads(detail or "{}")
        except ValueError:
            result = {}
        updated += int(result.get("updated") or 0)
        matched = {str(value) for value in result.get("matchedExternalUserIds", [])}
        for profile in batch:
            external_id = str(profile.get("externalUserId") or "")
            if external_id in matched:
                checkpoint = mark_history_thread_complete(checkpoint_path, checkpoint, external_id)
            else:
                scan_ok = False

    for _ in range(120):
        rows = await _conversation_rows(page)
        pending_profiles: list[dict] = []
        for row in rows:
            row_key = hashlib.sha256(str(row.get("label") or "").encode("utf-8")).hexdigest()
            position_key = f"{row.get('index')}:{row_key}"
            if position_key in seen_positions:
                continue
            seen_positions.add(position_key)
            fresh_rows = await _conversation_rows(page)
            fresh_row = next((candidate for candidate in fresh_rows if candidate.get("label") == row.get("label")), None)
            if fresh_row is None:
                scan_ok = False
                continue
            try:
                thread_id = await _open_meta_conversation(page, fresh_row, "instagram")
                profile_ids.add(thread_id)
                display_name = _usable_meta_name(fresh_row.get("displayName"))
                avatar_url = str(
                    fresh_row.get("avatarUrl") or await _active_avatar_url(page, display_name) or ""
                ).strip()
                if not avatar_url.startswith(("https://", "http://")):
                    missing += 1
                    continue
                detected_ids.add(thread_id)
                pending_profiles.append({"externalUserId": thread_id, "avatarUrl": avatar_url[:2000]})
                if len(pending_profiles) >= 100:
                    await post_batch(pending_profiles)
                    pending_profiles = []
            except Exception as exc:
                scan_ok = False
                print(f"⚠️ Chưa lấy được avatar của một hội thoại Instagram: {type(exc).__name__}.", flush=True)
        if pending_profiles:
            await post_batch(pending_profiles)

        scroll = await _scroll_meta_list(page)
        if scroll is None:
            if rows:
                break
            scan_ok = False
            break
        if scroll["top"] + scroll["client"] >= scroll["height"] - 4:
            stable_bottom += 1
        else:
            stable_bottom = 0
        if stable_bottom >= 2:
            break
        await page.wait_for_timeout(320)

    complete = scan_ok and stable_bottom >= 2 and missing == 0 and len(detected_ids) == len(profile_ids)
    if complete:
        mark_history_complete(checkpoint_path)
    return {
        "complete": complete,
        "scanned": len(profile_ids),
        "detected": len(detected_ids),
        "updated": updated,
        "missing": missing,
    }


async def _import_history(
    page,
    channel_type: str,
    backend_url: str,
    connector_token: str,
    checkpoint_path: Path,
    checkpoint: dict,
    *,
    scroll_oldest: bool,
    display_name: str = "",
    avatar_url: str = "",
    mark_latest_inbound_live: bool = False,
) -> tuple[dict, int]:
    channel_name = _channel_name(channel_type)
    thread_id = await _active_thread_id(page)
    if not thread_id:
        raise RuntimeError("Meta không cung cấp mã hội thoại đang mở.")
    display_name = _usable_meta_name(display_name) or _usable_meta_name(await _active_display_name(page, ""))
    avatar_url = str(avatar_url or await _active_avatar_url(page, display_name) or "")
    rows = (
        await _collect_meta_history_rows(
            page, channel_type, thread_id, display_name, avatar_url, scroll_oldest=True
        )
        if scroll_oldest
        else await _visible_message_rows(page, channel_type, thread_id, display_name, avatar_url)
    )
    history = normalize_meta_history(channel_type, thread_id, thread_id, display_name, rows)
    if not history:
        raise RuntimeError(f"{channel_name} chưa đọc được tin nhắn lịch sử; chưa đánh dấu hội thoại hoàn tất.")
    live_message_ids: set[str] = set()
    if mark_latest_inbound_live:
        latest_inbound = next(
            (item for item in reversed(history) if item.get("direction") == "inbound"),
            None,
        )
        if latest_inbound and latest_inbound.get("messageId"):
            live_message_ids.add(str(latest_inbound["messageId"]))
    for start in range(0, len(history), 100):
        status, detail = await asyncio.to_thread(
            _send_history,
            channel_type,
            backend_url,
            connector_token,
            history[start:start + 100],
            live_message_ids=live_message_ids,
        )
        if not 200 <= status < 300:
            raise RuntimeError(f"CRM từ chối lô lịch sử {channel_name} (HTTP {status}): {detail[:160]}")
    if scroll_oldest:
        checkpoint = mark_history_thread_complete(checkpoint_path, checkpoint, thread_id)
    return checkpoint, len(history)


async def _scan_loaded_conversations(
    page, channel_type: str, backend_url: str, token: str, checkpoint_path: Path,
    profile_cache: dict[str, dict] | None = None,
) -> bool:
    checkpoint = load_history_checkpoint(checkpoint_path)
    completed = set(str(value) for value in checkpoint.get("completed_threads", []))
    imported_threads = 0
    seen_positions: set[str] = set()
    profile_thread_ids: set[str] = set()
    avatar_thread_ids: set[str] = set()
    stable_bottom = 0
    scan_ok = True
    await page.evaluate(
        r"""() => {
          const vw=innerWidth,vh=innerHeight;
          const list=[...document.querySelectorAll('*')].filter(e=>{const r=e.getBoundingClientRect();return e.scrollHeight>e.clientHeight+30&&r.x<vw*.38&&r.width>vw*.14&&r.width<vw*.4&&r.y>80&&r.height>vh*.3}).sort((a,b)=>b.clientHeight-a.clientHeight)[0];
          if(list) list.scrollTop=0;
        }"""
    )
    await page.wait_for_timeout(500)
    channel_name = _channel_name(channel_type)
    print(f"📚 Đang nhập lịch sử {channel_name} trong Meta Business Suite…", flush=True)
    for _ in range(120):
        rows = await _conversation_rows(page)
        for row in rows:
            row_key = hashlib.sha256(str(row.get("label") or "").encode("utf-8")).hexdigest()
            position_key = f"{row.get('index')}:{row_key}"
            if position_key in seen_positions:
                continue
            seen_positions.add(position_key)
            try:
                fresh_rows = await _conversation_rows(page)
                fresh_row = next((candidate for candidate in fresh_rows if candidate.get("label") == row.get("label")), None)
                if fresh_row is None:
                    scan_ok = False
                    continue
                thread_id = await _open_meta_conversation(page, fresh_row, channel_type)
                display_name = _usable_meta_name(fresh_row.get("displayName"))
                avatar_url = str(fresh_row.get("avatarUrl") or await _active_avatar_url(page, display_name) or "")
                profile_thread_ids.add(thread_id)
                if avatar_url:
                    avatar_thread_ids.add(thread_id)
                if profile_cache is not None and (display_name or avatar_url):
                    profile_cache[thread_id] = {"displayName": display_name, "avatarUrl": avatar_url}
                checkpoint, count = await _import_history(
                    page, channel_type, backend_url, token, checkpoint_path, checkpoint,
                    scroll_oldest=thread_id not in completed,
                    display_name=display_name,
                    avatar_url=avatar_url,
                )
                if thread_id not in completed:
                    completed.add(thread_id)
                    imported_threads += 1
                    print(f"✅ Đã nhập lịch sử {channel_name} ({count} tin hiện có).", flush=True)
            except Exception as exc:
                scan_ok = False
                print(f"⚠️ Chưa nhập được một hội thoại Meta; sẽ thử lại ở lần quét sau: {type(exc).__name__}: {str(exc)[:180]}.", flush=True)
        scroll = await _scroll_meta_list(page)
        if scroll is None:
            if rows:
                return scan_ok
            raise RuntimeError(f"Không nhận diện được danh sách hội thoại {channel_name} trong Meta Business Suite.")
        if scroll["top"] + scroll["client"] >= scroll["height"] - 4:
            stable_bottom += 1
        else:
            stable_bottom = 0
        if stable_bottom >= 2:
            break
        await page.wait_for_timeout(350)
    if channel_type == "instagram":
        print(
            f"📷 Đã nhận diện avatar Instagram cho {len(avatar_thread_ids)}/{len(profile_thread_ids)} hội thoại đang quét.",
            flush=True,
        )
    print(f"📚 Đã xử lý {imported_threads} hội thoại Meta đang tải; bridge tiếp tục theo dõi tin mới.", flush=True)
    return scan_ok and stable_bottom >= 2


async def _sync_changed_conversations(
    page, channel_type: str, backend_url: str, connector_token: str,
    checkpoint_path: Path, observed_rows: dict[str, str], rows: list[dict],
    profile_cache: dict[str, dict],
) -> None:
    row_signatures = {
        str(row.get("index")): hashlib.sha256(
            str(row.get("label") or "").encode("utf-8")
        ).hexdigest()
        for row in rows
    }
    if not observed_rows:
        observed_rows.update(row_signatures)
        return

    changed = [
        row for row in rows
        if observed_rows.get(str(row.get("index"))) != row_signatures.get(str(row.get("index")))
    ]
    for row in changed[:5]:
        row_key = str(row.get("index"))
        try:
            fresh_rows = await _conversation_rows(page)
            fresh_row = next((candidate for candidate in fresh_rows if candidate.get("label") == row.get("label")), None)
            if fresh_row is None:
                continue
            thread_id = await _open_meta_conversation(page, fresh_row, channel_type)
            profile = {
                "displayName": _usable_meta_name(fresh_row.get("displayName")),
                "avatarUrl": str(fresh_row.get("avatarUrl") or ""),
            }
            if profile["displayName"] or profile["avatarUrl"]:
                profile_cache[thread_id] = profile
            history_checkpoint = load_history_checkpoint(checkpoint_path)
            history_checkpoint, count = await _import_history(
                page, channel_type, backend_url, connector_token,
                checkpoint_path, history_checkpoint, scroll_oldest=False,
                display_name=profile["displayName"], avatar_url=profile["avatarUrl"],
                mark_latest_inbound_live=True,
            )
            # A transient Meta navigation/ID error must not consume this row
            # change; the next poll can retry it instead of losing the event.
            observed_rows[row_key] = row_signatures[row_key]
            print(
                f"🔔 Đã cập nhật hội thoại {_channel_name(channel_type)} "
                f"({count} tin đang hiển thị).",
                flush=True,
            )
        except Exception as exc:
            print(
                f"⚠️ Chưa đồng bộ được hoạt động chat Meta mới: "
                f"{type(exc).__name__}: {str(exc)[:140]}.",
                flush=True,
            )


def _select_channel_type() -> str:
    executable_name = Path(sys.executable if getattr(sys, "frozen", False) else sys.argv[0]).stem.casefold()
    if executable_name == "smartmerchantmessenger":
        return "facebook"
    if executable_name == "smartmerchantinstagram":
        return "instagram"
    inherited = os.getenv("SMART_MERCHANT_CHANNEL_TYPE", "").strip().lower()
    if inherited in {"facebook", "instagram"}:
        return inherited
    supplied = next((str(arg).split("=", 1)[1] for arg in sys.argv[1:] if arg.startswith("--channel=")), "")
    if supplied in {"facebook", "instagram"}:
        return supplied
    print("Chọn hộp thư sẽ kết nối: 1) Facebook Messenger  2) Instagram", flush=True)
    choice = input("Nhập 1 hoặc 2: ").strip()
    if choice not in {"1", "2"}:
        raise SystemExit("Vui lòng chọn 1 (Messenger) hoặc 2 (Instagram).")
    return "facebook" if choice == "1" else "instagram"


async def run() -> None:
    channel_type = _select_channel_type()
    os.environ["SMART_MERCHANT_CHANNEL_TYPE"] = channel_type
    channel_label = "Messenger" if channel_type == "facebook" else "Instagram"
    print(f"SmartMerchantMetaBusinessSuite build: Meta Business Suite · {channel_label}", flush=True)
    from playwright.async_api import async_playwright

    config_filename = f"{channel_type}_connector_config.json"
    backend_url, connector_token = configure_local_connector(
        channel_type, RUNTIME, PACKAGE_DIR, config_filename=config_filename
    )
    # Parser-versioned checkpoints make the history pass resumable; completed
    # histories must not be reopened on every connector restart.
    checkpoint_path = history_checkpoint_path(
        RUNTIME, channel_type, f"{connector_token}:{META_HISTORY_PARSER_REVISION}"
    )
    avatar_checkpoint_path = history_checkpoint_path(
        RUNTIME, channel_type, f"{connector_token}:instagram-avatar-backfill-v1"
    )
    history_checkpoint = load_history_checkpoint(checkpoint_path)
    avatar_checkpoint = load_history_checkpoint(avatar_checkpoint_path)
    monitor_conversation_changes = True
    history_scan_started = bool(history_checkpoint.get("complete"))
    if history_scan_started:
        print("✅ Lịch sử Meta đã đồng bộ trước đó; bỏ qua quét tin cũ và chỉ theo dõi tin mới.", flush=True)
    else:
        print("📚 Sẽ nhập lịch sử Meta còn thiếu một lần; luồng tin mới vẫn chạy song song. Meta có thể đánh dấu tin chưa đọc thành đã đọc.", flush=True)
    history_scan_task: asyncio.Task | None = None
    history_scan_page = None
    avatar_scan_task: asyncio.Task | None = None
    avatar_scan_page = None
    avatar_scan_started = bool(avatar_checkpoint.get("complete"))
    port_variable = "META_MESSENGER_CDP_PORT" if channel_type == "facebook" else "META_INSTAGRAM_CDP_PORT"
    port = int(os.getenv(port_variable, "9224" if channel_type == "facebook" else "9225"))
    report_connector_status(channel_type, backend_url, connector_token)
    async with async_playwright() as playwright:
        while True:
            try:
                if not _cdp_ready(port):
                    await asyncio.to_thread(_start_edge, channel_type, port)
                browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                if not browser.contexts:
                    raise RuntimeError("Edge chưa có browser context.")
                context = browser.contexts[0]
                inbox_pages = [item for item in context.pages if _inbox_state(item) == "inbox"]
                page = next((item for item in inbox_pages if _is_channel_inbox_url(channel_type, item.url)), None)
                if page is None and inbox_pages:
                    page = inbox_pages[0]
                if page is None:
                    page = await context.new_page()
                    await page.goto(_meta_inbox_url(channel_type), wait_until="domcontentloaded", timeout=120000)
                desired = _meta_inbox_url(channel_type, page.url)
                if not _is_channel_inbox_url(channel_type, page.url):
                    await page.goto(desired, wait_until="domcontentloaded", timeout=120000)
                _start_control_server(page, channel_type, connector_token)
                if _inbox_state(page) == "login":
                    print("🔐 Hãy đăng nhập hoặc xử lý xác minh thủ công trong Edge; connector đang chờ.", flush=True)
                print(f"Meta Business Suite · {channel_label} connector đang theo dõi inbox; Ctrl+C để dừng.", flush=True)
                announced_inbox = False
                observed_threads: dict[str, str] = {}
                observed_message_ids: dict[str, set[str]] = {}
                observed_rows: dict[str, str] = {}
                profile_cache: dict[str, dict] = {}
                while _cdp_ready(port) and not page.is_closed():
                    state = _inbox_state(page)
                    if state == "login":
                        await asyncio.sleep(5)
                        continue
                    if state != "inbox":
                        print("ℹ️ Hãy mở lại Meta Business Suite Inbox trong Edge để connector tiếp tục.", flush=True)
                        await asyncio.sleep(5)
                        continue
                    if not _is_channel_inbox_url(channel_type, page.url):
                        await page.goto(_meta_inbox_url(channel_type, page.url), wait_until="domcontentloaded", timeout=120000)
                        await page.wait_for_timeout(500)
                        if not _is_channel_inbox_url(channel_type, page.url):
                            print(f"⚠️ Edge chưa mở đúng inbox {channel_label}; chưa đọc để tránh nhập nhầm kênh.", flush=True)
                            await asyncio.sleep(5)
                            continue
                    if not announced_inbox:
                        print(f"✅ Đang ở inbox {channel_label} của Meta Business Suite.", flush=True)
                        announced_inbox = True
                    if (
                        channel_type == "instagram"
                        and not avatar_scan_started
                        and history_scan_task is None
                        and load_history_checkpoint(checkpoint_path).get("complete")
                    ):
                        avatar_scan_started = True
                        try:
                            avatar_scan_page = await context.new_page()
                            await avatar_scan_page.goto(
                                _meta_inbox_url(channel_type, page.url),
                                wait_until="domcontentloaded",
                                timeout=120000,
                            )
                            await avatar_scan_page.wait_for_timeout(700)
                            avatar_scan_task = asyncio.create_task(
                                _scan_instagram_profile_avatars(
                                    avatar_scan_page,
                                    backend_url,
                                    connector_token,
                                    avatar_checkpoint_path,
                                )
                            )
                            await page.bring_to_front()
                            print("📷 Đang cập nhật avatar Instagram còn thiếu; lịch sử tin nhắn không được quét lại.", flush=True)
                        except Exception as exc:
                            avatar_scan_started = False
                            if avatar_scan_page is not None:
                                try:
                                    await avatar_scan_page.close()
                                except Exception:
                                    pass
                            avatar_scan_page = None
                            print(f"⚠️ Chưa khởi động được lượt cập nhật avatar Instagram: {type(exc).__name__}.", flush=True)
                    rows = await _conversation_rows(page)
                    if monitor_conversation_changes:
                        await _sync_changed_conversations(
                            page, channel_type, backend_url, connector_token,
                            checkpoint_path, observed_rows, rows, profile_cache,
                        )
                    if rows and not history_scan_started:
                        history_scan_started = True
                        try:
                            history_scan_page = await context.new_page()
                            await history_scan_page.goto(
                                _meta_inbox_url(channel_type, page.url),
                                wait_until="domcontentloaded",
                                timeout=120000,
                            )
                            await history_scan_page.wait_for_timeout(700)
                            history_scan_task = asyncio.create_task(
                                _scan_loaded_conversations(
                                    history_scan_page, channel_type, backend_url, connector_token,
                                    checkpoint_path, profile_cache,
                                )
                            )
                            await page.bring_to_front()
                            print("📚 Đang nhập lịch sử trên tab nền; tab theo dõi tin mới không bị gián đoạn.", flush=True)
                        except Exception as exc:
                            if history_scan_page is not None:
                                try:
                                    await history_scan_page.close()
                                except Exception:
                                    pass
                            history_scan_page = None
                            print(f"⚠️ Chưa khởi động được lượt nhập lịch sử Meta: {type(exc).__name__}: {str(exc)[:160]}. Tin mới vẫn được theo dõi; lịch sử còn thiếu sẽ tiếp tục khi khởi chạy lại.", flush=True)
                    if history_scan_task is not None and history_scan_task.done():
                        scan_task = history_scan_task
                        history_scan_task = None
                        try:
                            if scan_task.result():
                                mark_history_complete(checkpoint_path)
                                print(f"✅ Đã nhập xong lịch sử {channel_label}; từ giờ chỉ đồng bộ tin mới.", flush=True)
                            else:
                                print(f"⚠️ Lượt nhập lịch sử {channel_label} còn hội thoại chưa đọc được. Đã lưu checkpoint; bridge vẫn theo dõi tin mới và chỉ tiếp tục phần còn thiếu khi khởi chạy lại.", flush=True)
                        except Exception as exc:
                            print(f"⚠️ Lượt nhập lịch sử {channel_label} bị gián đoạn: {type(exc).__name__}: {str(exc)[:160]}. Bridge vẫn theo dõi tin mới; phần còn thiếu sẽ tiếp tục khi khởi chạy lại.", flush=True)
                        finally:
                            if history_scan_page is not None:
                                try:
                                    await history_scan_page.close()
                                except Exception:
                                    pass
                            history_scan_page = None
                    if avatar_scan_task is not None and avatar_scan_task.done():
                        scan_task = avatar_scan_task
                        avatar_scan_task = None
                        try:
                            result = scan_task.result()
                            print(
                                f"📷 Instagram: thấy ảnh {result['detected']}/{result['scanned']} hội thoại, "
                                f"CRM cập nhật {result['updated']} avatar."
                                + (" Còn hội thoại thiếu ảnh; checkpoint sẽ tiếp tục ở lần chạy sau." if not result["complete"] else ""),
                                flush=True,
                            )
                        except Exception as exc:
                            print(f"⚠️ Lượt cập nhật avatar Instagram bị gián đoạn: {type(exc).__name__}: {str(exc)[:140]}.", flush=True)
                        finally:
                            if avatar_scan_page is not None:
                                try:
                                    await avatar_scan_page.close()
                                except Exception:
                                    pass
                            avatar_scan_page = None
                    current_id = await _active_thread_id(page)
                    if current_id:
                        profile = profile_cache.get(current_id, {})
                        name = _usable_meta_name(profile.get("displayName")) or _usable_meta_name(await _active_display_name(page, ""))
                        avatar_url = str(profile.get("avatarUrl") or await _active_avatar_url(page, name) or "")
                        messages = await _visible_message_rows(page, channel_type, current_id, name, avatar_url)
                        signature = hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
                        if observed_threads.get(current_id) != signature:
                            current_message_ids = {
                                str(item.get("messageId") or "")
                                for item in messages
                                if item.get("messageId")
                            }
                            previous_message_ids = observed_message_ids.get(current_id)
                            live_message_ids = {
                                str(item.get("messageId") or "")
                                for item in messages
                                if item.get("messageId")
                                and item.get("direction") == "inbound"
                                and previous_message_ids is not None
                                and str(item.get("messageId")) not in previous_message_ids
                            }
                            status, detail = await asyncio.to_thread(
                                _send_history,
                                channel_type,
                                backend_url,
                                connector_token,
                                messages,
                                live_message_ids=live_message_ids,
                            ) if messages else (200, "")
                            if 200 <= status < 300:
                                observed_threads[current_id] = signature
                                observed_message_ids[current_id] = current_message_ids
                            elif detail:
                                print(f"⚠️ CRM chưa nhận được tin {channel_label} (HTTP {status}).", flush=True)
                        elif current_id not in observed_message_ids:
                            observed_message_ids[current_id] = {
                                str(item.get("messageId") or "")
                                for item in messages
                                if item.get("messageId")
                            }
                    await asyncio.sleep(3)
                report_connector_status(channel_type, backend_url, connector_token, state="error", error_code="edge_disconnected")
                if history_scan_task is not None and not history_scan_task.done():
                    history_scan_task.cancel()
                    await asyncio.gather(history_scan_task, return_exceptions=True)
                    history_scan_task = None
                    if history_scan_page is not None:
                        try:
                            await history_scan_page.close()
                        except Exception:
                            pass
                    history_scan_page = None
                    if not load_history_checkpoint(checkpoint_path).get("complete"):
                        history_scan_started = False
                if avatar_scan_task is not None and not avatar_scan_task.done():
                    avatar_scan_task.cancel()
                    await asyncio.gather(avatar_scan_task, return_exceptions=True)
                    avatar_scan_task = None
                    if avatar_scan_page is not None:
                        try:
                            await avatar_scan_page.close()
                        except Exception:
                            pass
                    avatar_scan_page = None
                    if not load_history_checkpoint(avatar_checkpoint_path).get("complete"):
                        avatar_scan_started = False
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"⚠️ Meta Business Suite connector tạm dừng: {type(exc).__name__}: {str(exc)[:180]}", flush=True)
                report_connector_status(channel_type, backend_url, connector_token, state="error", error_code=type(exc).__name__.lower())
                await asyncio.sleep(10)


def self_test() -> None:
    from playwright.async_api import async_playwright
    del async_playwright
    if _meta_inbox_url("facebook").find("/messenger") < 0 or _meta_inbox_url("instagram").find("/instagram_direct") < 0:
        raise SystemExit("Sai cấu hình Meta Business Suite.")
    print("Smart Merchant Meta Business Suite: ứng dụng và cấu hình đã sẵn sàng.")


if __name__ == "__main__" and "--self-test" in sys.argv:
    self_test()
elif __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("Đã dừng Meta Business Suite connector.", flush=True)
