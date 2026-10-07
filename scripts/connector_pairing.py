"""Small stdlib-only first-run pairing helper for local channel connectors."""

from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path
from threading import Event, Thread
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse


_HEARTBEAT_THREADS: set[str] = set()


def _is_pairing_code_for_channel(value: str, channel_type: str) -> bool:
    return bool(re.fullmatch(
        rf"PAIR\.{re.escape(channel_type)}\.\d+\.\d+\.[A-Za-z0-9_-]{{12,}}",
        str(value or "").strip(),
    ))


def order_checkpoint_path(runtime_dir: Path, channel_type: str, connector_token: str) -> Path:
    fingerprint = hashlib.sha256(str(connector_token).encode("utf-8")).hexdigest()[:16]
    return runtime_dir / f"{channel_type}-orders-{fingerprint}.json"


def load_order_checkpoint(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and value.get("version") == 1:
            return value
    except (OSError, ValueError, TypeError):
        pass
    return {"version": 1, "synced_order_ids": [], "last_sync_at": None}


def _marketplace_order_fingerprint(order: dict) -> str:
    encoded = json.dumps(order, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def marketplace_orders_pending(checkpoint: dict, orders: list[dict]) -> list[dict]:
    fingerprints = checkpoint.get("order_fingerprints", {})
    if not isinstance(fingerprints, dict):
        fingerprints = {}
    return [
        order for order in orders
        if fingerprints.get(str(order.get("external_order_id") or "")) != _marketplace_order_fingerprint(order)
    ]


def save_order_checkpoint(path: Path, checkpoint: dict, orders: list[dict]) -> dict:
    """Save a bounded per-shop receipt checkpoint after CRM accepted the batch."""
    prior_fingerprints = checkpoint.get("order_fingerprints", {})
    fingerprints = dict(prior_fingerprints) if isinstance(prior_fingerprints, dict) else {}
    for order in orders:
        order_id = str(order.get("external_order_id") or "")
        if order_id:
            fingerprints[order_id] = _marketplace_order_fingerprint(order)
    known = list(dict.fromkeys(
        [str(value) for value in checkpoint.get("synced_order_ids", [])]
        + [str(order.get("external_order_id") or "") for order in orders if order.get("external_order_id")]
    ))[-5000:]
    updated = {
        "version": 1,
        "synced_order_ids": known,
        "order_fingerprints": {order_id: fingerprints[order_id] for order_id in known if order_id in fingerprints},
        "last_sync_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix="orders-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as temporary:
            json.dump(updated, temporary, ensure_ascii=False, separators=(",", ":"))
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
    return updated


def post_marketplace_orders(
    channel_type: str,
    backend_url: str,
    connector_token: str,
    orders: list[dict],
) -> tuple[int, str]:
    request = Request(
        f"{backend_url.rstrip('/')}/api/channels/{channel_type}/orders",
        data=json.dumps({"orders": orders}, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Authorization": f"Bearer {connector_token}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:300]
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def normalize_visible_order_card(channel_type: str, card: dict) -> dict | None:
    """Extract only order essentials from rendered Seller Center card text."""
    text = str(card.get("text") or "")[:12000]
    order_id = str(card.get("orderId") or "").strip()
    if not order_id:
        match = re.search(
            r"(?:mã\s*đơn\s*hàng|id\s*đơn\s*hàng|order\s*(?:id|no\.?))\s*[:#\s]*([a-z0-9-]{6,})",
            text,
            re.IGNORECASE,
        )
        order_id = match.group(1).strip() if match else ""
    if not order_id or len(order_id) > 255:
        return None

    def amount(value: str) -> int:
        digits = re.sub(r"\D", "", value)
        return int(digits) if digits else 0

    def currency_amounts(value: str) -> list[int]:
        results: list[tuple[int, int]] = []
        prefix_pattern = re.compile(r"(?:₫|đ|vnd)\s*([\d][\d.,]*)", re.IGNORECASE)
        suffix_pattern = re.compile(r"([\d][\d.,]*)\s*(?:₫|đ|vnd)", re.IGNORECASE)
        for match in prefix_pattern.finditer(value):
            results.append((match.start(), amount(match.group(1))))
        for match in suffix_pattern.finditer(value):
            number_start = match.start(1)
            # In rows like “x1 ₫349.000”, don't mistake the quantity before
            # the currency symbol for a price. Prefix-currency matching above
            # still captures the actual price after the symbol.
            if re.search(r"[x×]\s*$", value[max(0, number_start - 8):number_start], re.IGNORECASE):
                continue
            results.append((match.start(), amount(match.group(1))))
        return [price for _, price in sorted(results)]

    money_values = currency_amounts(text)
    total_label = re.search(
        r"(?:tổng\s*(?:số\s*)?tiền(?:\s*người\s*mua\s*thanh\s*toán)?|order\s*total|total\s*payment)"
        r"[^\d₫đv]*((?:₫|đ|vnd)?\s*[\d][\d.,]*\s*(?:₫|đ|vnd)?)",
        text,
        re.IGNORECASE,
    )
    total_amount = amount(total_label.group(1)) if total_label else 0
    if total_amount == 0 and money_values:
        total_amount = money_values[-1]

    status = str(card.get("status") or "").strip()
    if not status:
        status = next((value for value in (
            "Chờ xác nhận", "Chờ lấy hàng", "Đang giao", "Đã giao", "Đã hoàn thành",
            "Đã hủy", "Đã huỷ", "Pending", "To ship", "Shipping", "Delivered", "Completed", "Cancelled",
        ) if re.search(re.escape(value), text, re.IGNORECASE)), "unknown")

    blocks = card.get("productBlocks") if isinstance(card.get("productBlocks"), list) else []
    items = []
    for block in blocks[:100]:
        lines = [" ".join(line.split()) for line in str(block or "").splitlines() if line.strip()]
        if not lines:
            continue
        name = next((line for line in lines if not re.search(
            r"^(?:sản phẩm|product|sku|mã sku|phân loại|variant|trạng thái|status)\b", line, re.IGNORECASE
        )), lines[0])
        name = re.sub(r"\s+(?:x|×)\s*\d+\s*$", "", name).strip()[:255]
        quantity_match = re.search(r"(?:x|×)\s*(\d{1,6})\b|(?:số lượng|qty)\s*[:x]?\s*(\d{1,6})", " ".join(lines), re.IGNORECASE)
        quantity = int(next(value for value in quantity_match.groups() if value)) if quantity_match else 1
        item_money = currency_amounts(" ".join(lines))
        unit_price = item_money[-1] if item_money else 0
        sku_match = re.search(r"(?:sku|mã sku)\s*[:#]?\s*([\w.-]{1,80})", " ".join(lines), re.IGNORECASE)
        items.append({
            "external_product_id": str(card.get("productId") or "")[:255] or None,
            "sku": sku_match.group(1)[:80] if sku_match else None,
            "name": name or f"Sản phẩm {channel_type.title()}",
            "quantity": max(1, quantity),
            "unit_price": unit_price,
        })

    if not items:
        # Keep the order visible in CRM even when a marketplace changes its
        # product-card markup; the true total stays on the order, not inventory.
        items = [{
            "external_product_id": None,
            "sku": None,
            "name": f"Đơn {channel_type.title()} {order_id}",
            "quantity": 1,
            "unit_price": total_amount,
        }]
    def iso_datetime(key: str) -> str | None:
        value = str(card.get(key) or "").strip()
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        except ValueError:
            return None

    return {
        "external_order_id": order_id,
        "buyer_id": str(card.get("buyerId") or "")[:255] or None,
        "source_status": status[:80],
        "total_amount": total_amount,
        "created_at": iso_datetime("createdAt"),
        "updated_at": iso_datetime("updatedAt"),
        "items": items,
    }


async def read_visible_marketplace_orders(page, channel_type: str) -> tuple[str, list[dict]]:
    """Read rendered order cards only; never inspect or call site API endpoints."""
    snapshot = await page.evaluate(
        r"""channel => {
          const visible = element => {
            const rect = element.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0 && getComputedStyle(element).visibility !== 'hidden';
          };
          const body = document.body?.innerText || '';
          const host = location.hostname.toLowerCase();
          if (/\/account\/login|\/login(?:\?|$)/i.test(location.pathname) ||
              (channel === 'shopee' && host !== 'banhang.shopee.vn') ||
              (channel === 'tiktok' && host !== 'seller-vn.tiktok.com'))
            return {state:'login',cards:[]};
          if ([...document.querySelectorAll('iframe[src*="captcha" i],[class*="captcha" i],[id*="captcha" i]')].some(visible)
            || [...document.querySelectorAll('[role="dialog"],[class*="modal" i]')].some(el => visible(el) && /(captcha|security verification|verify you are human|slide to verify|xác minh bảo mật|kéo thanh trượt)/i.test(el.innerText || '')))
            return {state:'challenge',cards:[]};
          const selectors = channel === 'shopee'
            ? '.order-list-card,.order-card,.order-item-card,[data-order-id],[data-order-sn],tr,[role="row"]'
            : '[data-order-id],[data-testid*="order" i],[class*="order-card" i],[class*="order-item" i],tr,[role="row"]';
          const candidates = [...document.querySelectorAll(selectors)].filter(element => {
            if (!visible(element)) return false;
            const text = (element.innerText || '').trim();
            return text.length >= 20 && text.length <= 5000;
          });
          const byId = new Map();
          for (const element of candidates) {
            const text = (element.innerText || '').trim();
            let orderId = element.getAttribute('data-order-id') || element.getAttribute('data-order-sn') || element.getAttribute('data-orderid') || '';
            if (!orderId) {
              const child = element.querySelector('[data-order-id],[data-order-sn],[data-orderid]');
              orderId = child?.getAttribute('data-order-id') || child?.getAttribute('data-order-sn') || child?.getAttribute('data-orderid') || '';
            }
            if (!orderId) {
              const match = text.match(/(?:mã\s*đơn\s*hàng|id\s*đơn\s*hàng|order\s*(?:id|no\.?))\s*[:#\s]*([a-z0-9-]{6,})/i);
              orderId = match?.[1] || '';
            }
            if (!orderId) continue;
            const productBlocks = [...element.querySelectorAll('[class*="product" i],[class*="item-card" i],[data-testid*="product" i],[data-cy*="product" i]')]
              .filter(visible)
              .map(node => (node.innerText || '').trim())
              .filter(value => value.length > 2 && value.length < 2000)
              .filter((value,index,all) => all.indexOf(value) === index)
              .slice(0,100);
            const attrs = element.attributes;
            const statusNode = [...element.querySelectorAll('[class*="status" i],[data-testid*="status" i]')].find(visible);
            const createdAt = element.getAttribute('data-created-at') || element.getAttribute('data-create-time') || '';
            const productId = element.getAttribute('data-product-id') || '';
            const candidate = {orderId:String(orderId).trim(),text,productBlocks,status:(statusNode?.innerText || '').trim(),createdAt,productId};
            const prior = byId.get(candidate.orderId);
            if (!prior || candidate.productBlocks.length > prior.productBlocks.length || candidate.text.length > prior.text.length)
              byId.set(candidate.orderId,candidate);
          }
          const cards = [...byId.values()];
          const noOrders = /(?:không có đơn hàng|chưa có đơn hàng|không có dữ liệu|0 đơn hàng|no orders?|no data)/i.test(body);
          return {state:cards.length ? 'ready' : noOrders ? 'empty' : 'unrecognized',cards};
        }""",
        channel_type,
    )
    state = str(snapshot.get("state") or "unknown") if isinstance(snapshot, dict) else "unknown"
    rows = snapshot.get("cards", []) if isinstance(snapshot, dict) else []
    normalized = []
    for card in rows:
        order = normalize_visible_order_card(channel_type, card)
        if order is not None:
            normalized.append(order)
    return state, normalized


def history_checkpoint_path(runtime_dir: Path, channel_type: str, connector_token: str) -> Path:
    """Keep resumable import state isolated per paired shop without storing its token."""
    fingerprint = hashlib.sha256(str(connector_token).encode("utf-8")).hexdigest()[:16]
    return runtime_dir / f"{channel_type}-history-{fingerprint}.json"


def post_history_batch(
    channel_type: str,
    backend_url: str,
    connector_token: str,
    messages: list[dict],
    *,
    live_message_ids: set[str] | None = None,
) -> tuple[int, str]:
    """Send one bounded historical batch to the automation-free CRM import route."""
    live_ids = {str(value) for value in (live_message_ids or set())}
    payload_messages = []
    for message in messages:
        item = dict(message)
        message_id = str(item.get("messageId") or item.get("message_id") or "")
        if message_id in live_ids and str(item.get("direction") or "inbound").lower() == "inbound":
            # History and live discovery share idempotent persistence, but only
            # IDs explicitly identified by the foreground watcher are realtime.
            item["isLive"] = True
        payload_messages.append(item)
    request = Request(
        f"{backend_url.rstrip('/')}/api/channels/{channel_type}/history",
        data=json.dumps({"messages": payload_messages}, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "Authorization": f"Bearer {connector_token}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=45) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:300]
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def load_history_checkpoint(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and value.get("version") == 1:
            return value
    except (OSError, ValueError, TypeError):
        pass
    return {"version": 1, "completed_threads": [], "complete": False}


def mark_history_thread_complete(path: Path, checkpoint: dict, thread_id: str) -> dict:
    """Atomically persist only thread IDs; a crash before this safely replays via DB dedupe."""
    done = set(str(value) for value in checkpoint.get("completed_threads", []))
    done.add(str(thread_id))
    updated = {"version": 1, "completed_threads": sorted(done), "complete": False}
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix="history-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as temporary:
            json.dump(updated, temporary, ensure_ascii=False, separators=(",", ":"))
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
    return updated


def mark_history_complete(path: Path) -> None:
    checkpoint = load_history_checkpoint(path)
    checkpoint["complete"] = True
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix="history-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as temporary:
            json.dump(checkpoint, temporary, ensure_ascii=False, separators=(",", ":"))
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def report_connector_status(
    channel_type: str,
    backend_url: str,
    connector_token: str,
    *,
    state: str = "online",
    error_code: str | None = None,
    retry_ack_id: str | None = None,
) -> dict:
    if state not in {"online", "error"}:
        return {}
    payload = {"state": state}
    if error_code:
        payload["error_code"] = str(error_code)[:80]
    if retry_ack_id:
        payload["retry_ack_id"] = str(retry_ack_id)[:80]
    request = Request(
        f"{backend_url.rstrip('/')}/api/channels/{channel_type}/heartbeat",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {connector_token}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return {}


def _restart_connector_process() -> None:
    env = os.environ.copy()
    env["SMART_MERCHANT_AUTO_RESTART"] = "1"
    command = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, *sys.argv]
    subprocess.Popen(command, cwd=os.getcwd(), env=env, close_fds=True)
    os._exit(0)


def _acknowledge_retry_and_restart(channel_type: str, backend_url: str, connector_token: str, retry_id: str) -> bool:
    result = report_connector_status(
        channel_type, backend_url, connector_token, retry_ack_id=retry_id
    )
    if result.get("retry_acknowledged") is True:
        _restart_connector_process()
        return True
    return False


def start_connector_heartbeat(channel_type: str, backend_url: str, connector_token: str) -> None:
    if channel_type in _HEARTBEAT_THREADS:
        return
    _HEARTBEAT_THREADS.add(channel_type)

    def beat() -> None:
        stopped = Event()
        while not stopped.is_set():
            status = report_connector_status(channel_type, backend_url, connector_token)
            retry_id = str(status.get("retry_id") or "")
            if retry_id and _acknowledge_retry_and_restart(channel_type, backend_url, connector_token, retry_id):
                return
            stopped.wait(45)

    Thread(target=beat, name=f"{channel_type}-connector-heartbeat", daemon=True).start()


def configure_local_connector(
    channel_type: str,
    runtime_dir: Path,
    package_dir: Path,
    *,
    config_filename: str = "connector_config.json",
) -> tuple[str, str]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    config_path = runtime_dir / config_filename
    defaults_path = package_dir / "connector_defaults.json"
    try:
        defaults = json.loads(defaults_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        defaults = {}
    execution_mode = str(defaults.get("execution_mode") or "local").strip().lower()
    if execution_mode not in {"local", "server"}:
        raise SystemExit("Cấu hình connector không hợp lệ: execution_mode phải là local hoặc server.")

    # Server-managed workers receive their short-lived-at-rest credentials from
    # the Windows agent process. They must never prompt or persist the token.
    if os.getenv("SMART_MERCHANT_SERVER_WORKER") == "1":
        backend_url = str(os.getenv("SMART_MERCHANT_SERVER_BACKEND_URL") or "").strip().rstrip("/")
        connector_token = str(os.getenv("SMART_MERCHANT_SERVER_CONNECTOR_TOKEN") or "").strip()
        if not backend_url or not connector_token.startswith(f"CONN.{channel_type}."):
            raise SystemExit("Server agent chưa cấp cấu hình connector hợp lệ.")
        os.environ[f"{channel_type.upper()}_BACKEND_URL"] = backend_url
        os.environ[f"{channel_type.upper()}_CONNECTOR_TOKEN"] = connector_token
        start_connector_heartbeat(channel_type, backend_url, connector_token)
        return backend_url, connector_token

    pairing_code = ""
    if execution_mode == "local" and config_path.is_file():
        try:
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            backend_url = str(saved.get("backend_url") or "").strip().rstrip("/")
            connector_token = str(saved.get("connector_token") or "").strip()
            if backend_url and connector_token:
                automatic_restart = os.environ.pop("SMART_MERCHANT_AUTO_RESTART", "") == "1"
                answer = "" if automatic_restart else input(
                    "Đã có kết nối lưu trên máy này. Nhấn Enter để dùng, nhập R hoặc dán mã PAIR mới để ghép nối lại: "
                ).strip()
                if automatic_restart or not answer:
                    os.environ[f"{channel_type.upper()}_BACKEND_URL"] = backend_url
                    os.environ[f"{channel_type.upper()}_CONNECTOR_TOKEN"] = connector_token
                    start_connector_heartbeat(channel_type, backend_url, connector_token)
                    return backend_url, connector_token
                if answer.casefold() == "r":
                    pass
                elif _is_pairing_code_for_channel(answer, channel_type):
                    pairing_code = answer
                    print("Đã nhận mã ghép nối mới; đang xác thực lại connector…")
                else:
                    raise SystemExit(
                        "Lựa chọn không hợp lệ. Nhấn Enter để dùng kết nối đã lưu, nhập R hoặc dán đúng mã PAIR của kênh này."
                    )
        except (OSError, ValueError, TypeError):
            pass

    default_url = str(defaults.get("backend_url") or "http://127.0.0.1:8000").strip().rstrip("/")
    print("\nSmart Merchant — thiết lập kết nối lần đầu")
    print("Đang dùng địa chỉ hệ thống đã cấu hình sẵn. Mã ghép nối lấy trong mục Liên kết mạng xã hội.")
    backend_url = default_url
    backend_url = backend_url.rstrip("/")
    if backend_url.endswith("/api"):
        backend_url = backend_url[:-4]
    parsed = urlparse(backend_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise SystemExit("Địa chỉ Smart Merchant không hợp lệ.")

    if not pairing_code:
        pairing_code = input("Nhập pairing code trong mục Liên kết mạng xã hội: ").strip()
    if not pairing_code:
        raise SystemExit("Chưa nhập pairing code.")
    pair_payload = {"pairing_code": pairing_code}
    if execution_mode == "server":
        pair_payload["execution_mode"] = "server"
    request = Request(
        f"{backend_url}/api/channels/pair",
        data=json.dumps(pair_payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            paired = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise SystemExit(f"Ghép nối thất bại (HTTP {exc.code}): {detail}") from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise SystemExit(f"Không kết nối được Smart Merchant: {exc}") from exc

    if execution_mode == "server":
        if paired.get("channel_type") != channel_type or not paired.get("server_managed"):
            raise SystemExit("CRM chưa xác nhận ghép nối server-side cho kênh này.")
        viewer_ticket = str(paired.get("viewer_ticket") or "").strip()
        business_id = str(paired.get("business_id") or "").strip()
        channel_id = str(paired.get("channel_id") or "").strip()
        frontend_url = str(defaults.get("frontend_url") or "").strip().rstrip("/")
        if not viewer_ticket or not business_id or not channel_id or not frontend_url:
            raise SystemExit("CRM chưa trả đủ thông tin mở phiên đăng nhập trên server.")
        from urllib.parse import urlencode

        viewer_url = (
            f"{frontend_url}/server-connector-viewer.html#"
            + urlencode({
                "api": backend_url,
                "business": business_id,
                "channel": channel_id,
                "type": channel_type,
                "ticket": viewer_ticket,
            })
        )
        print("Đã ghép shop với server. Mở cửa sổ đăng nhập từ xa; token không được lưu trên máy này.", flush=True)
        opened = webbrowser.open(viewer_url)
        if opened:
            print("Hãy đăng nhập/xử lý xác minh trong cửa sổ đăng nhập từ xa, rồi có thể đóng EXE.", flush=True)
        else:
            print(f"Không tự mở được trình duyệt; hãy mở liên kết dùng một lần này: {viewer_url}", flush=True)
        raise SystemExit(0)

    connector_token = str(paired.get("connector_token") or "").strip()
    if paired.get("channel_type") != channel_type or not connector_token.startswith(f"CONN.{channel_type}."):
        raise SystemExit("CRM trả về cấu hình connector không hợp lệ.")
    config_path.write_text(
        json.dumps({"backend_url": backend_url, "connector_token": connector_token}, indent=2),
        encoding="utf-8",
    )
    os.environ[f"{channel_type.upper()}_BACKEND_URL"] = backend_url
    os.environ[f"{channel_type.upper()}_CONNECTOR_TOKEN"] = connector_token
    start_connector_heartbeat(channel_type, backend_url, connector_token)
    print("Đã ghép nối. Mã truy cập được lưu trên máy này; không gửi file cấu hình cho người khác.")
    return backend_url, connector_token
