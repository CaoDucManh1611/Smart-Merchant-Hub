"""Private Windows host agent for server-managed marketplace/Meta connectors.

Run only on the Windows VPS that owns the Edge profiles. The agent polls the
CRM over HTTPS, starts one connector worker per paired shop/channel, and exposes
only authenticated send/viewer routes to the CRM backend. Restrict its inbound
port with Windows Firewall; never forward it or the Edge CDP ports publicly.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Lock, Thread
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


BASE = Path(__file__).resolve().parent


def _load_agent_config() -> dict:
    configured = str(os.getenv("SERVER_CONNECTOR_AGENT_CONFIG") or "").strip()
    default = Path(os.getenv("PROGRAMDATA", r"C:\ProgramData")) / "SmartMerchant" / "server-connector-agent.json"
    path = Path(configured) if configured else default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


_CONFIG = _load_agent_config()
BACKEND_URL = str(os.getenv("SERVER_CONNECTOR_BACKEND_URL") or _CONFIG.get("backend_url") or "").strip().rstrip("/")
AGENT_TOKEN = str(os.getenv("SERVER_CONNECTOR_AGENT_TOKEN") or _CONFIG.get("agent_token") or "").strip()
LISTEN_HOST = str(os.getenv("SERVER_CONNECTOR_AGENT_HOST") or _CONFIG.get("listen_host") or "127.0.0.1").strip()
LISTEN_PORT = int(os.getenv("SERVER_CONNECTOR_AGENT_PORT") or _CONFIG.get("listen_port") or "8095")
DATA_ROOT = Path(os.getenv("SERVER_CONNECTOR_DATA_DIR") or _CONFIG.get("data_dir") or (
    Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "SmartMerchant" / "server-connectors"
))
POLL_SECONDS = max(5, min(int(os.getenv("SERVER_CONNECTOR_AGENT_POLL_SECONDS", "15")), 120))
SUPPORTED = {"tiktok", "shopee", "facebook", "instagram"}
workers: dict[tuple[int, str, int], dict] = {}
workers_lock = Lock()


def _safe_key(business_id: int, channel_type: str, channel_id: int) -> tuple[int, str, int]:
    if channel_type not in SUPPORTED:
        raise ValueError("Unsupported channel")
    return int(business_id), channel_type, int(channel_id)


def _worker_ports(key: tuple[int, str, int]) -> tuple[int, int]:
    """Use stable per-channel ports so a surviving Edge profile remains attachable after agent restart."""
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    path = DATA_ROOT / "port-assignments.json"
    key_text = f"{key[0]}:{key[1]}:{key[2]}"
    try:
        mapping = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(mapping, dict):
            mapping = {}
    except (OSError, ValueError, TypeError):
        mapping = {}
    prior = mapping.get(key_text)
    if isinstance(prior, dict):
        try:
            return int(prior["cdp"]), int(prior["control"])
        except (KeyError, TypeError, ValueError):
            pass
    used = {
        int(value.get(field))
        for value in mapping.values() if isinstance(value, dict)
        for field in ("cdp", "control")
        if str(value.get(field, "")).isdigit()
    }
    digest = int(hashlib.sha256(key_text.encode()).hexdigest()[:8], 16)
    for attempt in range(20000):
        offset = (digest + attempt) % 20000
        pair = (20000 + offset, 40000 + offset)
        if not used.intersection(pair):
            mapping[key_text] = {"cdp": pair[0], "control": pair[1]}
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(mapping, separators=(",", ":")), encoding="utf-8")
            temporary.replace(path)
            return pair
    raise RuntimeError("No connector port pair available")


def _worker_script(channel_type: str) -> Path:
    names = {
        "tiktok": "tiktok_bot.py",
        "shopee": "shopee_bot.py",
        "facebook": "meta_business_suite_bridge.py",
        "instagram": "meta_business_suite_bridge.py",
    }
    path = BASE / names[channel_type]
    if not path.is_file():
        raise RuntimeError(f"Missing connector script: {path.name}")
    return path


def _terminate_worker(record: dict) -> None:
    process = record.get("process")
    if process is None or process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False,
            )
        else:
            process.terminate()
            process.wait(timeout=10)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _spawn_worker(item: dict) -> dict:
    business_id = int(item["business_id"])
    channel_id = int(item["channel_id"])
    channel_type = str(item["channel_type"])
    connector_token = str(item["connector_token"])
    key = _safe_key(business_id, channel_type, channel_id)
    identity = hashlib.sha256(connector_token.encode("utf-8")).hexdigest()
    prior = workers.get(key)
    if prior and prior.get("identity") == identity and prior["process"].poll() is None:
        return prior
    if prior:
        _terminate_worker(prior)

    runtime = DATA_ROOT / f"business-{business_id}" / f"{channel_type}-{channel_id}"
    runtime.mkdir(parents=True, exist_ok=True)
    cdp_port, control_port = _worker_ports(key)
    environment = os.environ.copy()
    # The shared agent credential is not needed by connector workers; keep the
    # trust boundary narrow if a worker process is inspected or compromised.
    environment.pop("SERVER_CONNECTOR_AGENT_TOKEN", None)
    environment.update({
        "SMART_MERCHANT_SERVER_WORKER": "1",
        "SMART_MERCHANT_SERVER_BACKEND_URL": BACKEND_URL,
        "SMART_MERCHANT_SERVER_CONNECTOR_TOKEN": connector_token,
        "SMART_MERCHANT_RUNTIME_DIR": str(runtime),
        "SMART_MERCHANT_CHANNEL_TYPE": channel_type,
        "TIKTOK_CDP_PORT": str(cdp_port),
        "TIKTOK_BRIDGE_CONTROL_PORT": str(control_port),
        "TIKTOK_BRIDGE_CONTROL_HOST": "127.0.0.1",
        "SHOPEE_CDP_PORT": str(cdp_port),
        "SHOPEE_BRIDGE_CONTROL_PORT": str(control_port),
        "SHOPEE_BRIDGE_CONTROL_HOST": "127.0.0.1",
        "META_MESSENGER_CDP_PORT": str(cdp_port),
        "META_INSTAGRAM_CDP_PORT": str(cdp_port),
        "META_MESSENGER_BRIDGE_CONTROL_PORT": str(control_port),
        "META_INSTAGRAM_BRIDGE_CONTROL_PORT": str(control_port),
        "META_BRIDGE_CONTROL_HOST": "127.0.0.1",
    })
    args = [sys.executable, str(_worker_script(channel_type))]
    if channel_type in {"facebook", "instagram"}:
        args.append(f"--channel={channel_type}")
    process = subprocess.Popen(
        args,
        cwd=str(BASE),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=None,
        stderr=None,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    record = {
        "key": key,
        "identity": identity,
        "process": process,
        "connector_token": connector_token,
        "cdp_port": cdp_port,
        "control_port": control_port,
        "runtime": runtime,
        "started_at": time.time(),
    }
    workers[key] = record
    print(f"Started server connector {business_id}/{channel_type}/{channel_id} (PID {process.pid})", flush=True)
    return record


def _sync_active_connectors() -> None:
    if not BACKEND_URL or not AGENT_TOKEN:
        raise RuntimeError("Set SERVER_CONNECTOR_BACKEND_URL and SERVER_CONNECTOR_AGENT_TOKEN first.")
    request = Request(
        f"{BACKEND_URL}/api/channels/server-managed/active",
        headers={"X-Server-Connector-Agent-Token": AGENT_TOKEN, "Accept": "application/json"},
    )
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    desired: dict[tuple[int, str, int], dict] = {}
    for item in payload.get("connectors", []):
        if not isinstance(item, dict):
            continue
        key = _safe_key(item.get("business_id"), str(item.get("channel_type") or ""), item.get("channel_id"))
        desired[key] = item
    with workers_lock:
        for key, item in desired.items():
            _spawn_worker(item)
        for key in set(workers) - set(desired):
            _terminate_worker(workers.pop(key))


def _poll_forever() -> None:
    while True:
        try:
            _sync_active_connectors()
        except (HTTPError, URLError, TimeoutError, ValueError, RuntimeError) as exc:
            print(f"Agent poll unavailable: {type(exc).__name__}", flush=True)
        except Exception as exc:
            print(f"Agent poll error: {type(exc).__name__}", flush=True)
        time.sleep(POLL_SECONDS)


def _authorized(headers) -> bool:
    supplied = str(headers.get("X-Server-Connector-Agent-Token") or "").strip()
    return bool(AGENT_TOKEN and supplied and hmac.compare_digest(AGENT_TOKEN, supplied))


def _record_for_path(parts: list[str]) -> dict | None:
    try:
        business_id, channel_type, channel_id = int(parts[2]), parts[3], int(parts[4])
        key = _safe_key(business_id, channel_type, channel_id)
    except (ValueError, IndexError, TypeError):
        return None
    with workers_lock:
        record = workers.get(key)
        return record if record and record["process"].poll() is None else None


class AgentHandler(BaseHTTPRequestHandler):
    server_version = "SmartMerchantWindowsAgent/1"

    def log_message(self, _format, *_args):
        # Do not log ticket values, message contents, or credentials.
        return

    def _reply(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._reply(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            self._json(200, {"status": "ok", "agent": "windows"})
            return
        if not _authorized(self.headers):
            self._json(401, {"detail": "Unauthorized"})
            return
        parts = path.strip("/").split("/")
        if len(parts) != 6 or parts[:2] != ["internal", "channels"] or parts[5] != "screenshot":
            self._json(404, {"detail": "Not found"})
            return
        record = _record_for_path(parts)
        if not record:
            self._json(503, {"detail": "Connector browser is not ready"})
            return
        try:
            image = asyncio.run(_capture_screenshot(record["cdp_port"]))
        except Exception as exc:
            self._json(503, {"detail": type(exc).__name__})
            return
        self._reply(200, image, "image/jpeg")

    def do_POST(self):
        path = urlsplit(self.path).path
        if not _authorized(self.headers):
            self._json(401, {"detail": "Unauthorized"})
            return
        parts = path.strip("/").split("/")
        if len(parts) != 6 or parts[:2] != ["internal", "channels"]:
            self._json(404, {"detail": "Not found"})
            return
        record = _record_for_path(parts)
        if not record:
            self._json(503, {"detail": "Connector worker is not ready"})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
            if length < 0 or length > 16384:
                raise ValueError("invalid body size")
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            if parts[5] == "send":
                channel_type = record["key"][1]
                secret_header = {
                    "tiktok": "X-TikTok-Bridge-Secret",
                    "shopee": "X-Shopee-Bridge-Secret",
                    "facebook": "X-Meta-Bridge-Secret",
                    "instagram": "X-Meta-Bridge-Secret",
                }[channel_type]
                request = Request(
                    f"http://127.0.0.1:{record['control_port']}/send",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json", secret_header: record["connector_token"]},
                    method="POST",
                )
                try:
                    with urlopen(request, timeout=35) as response:
                        self._reply(response.status, response.read())
                except HTTPError as exc:
                    self._reply(exc.code, exc.read())
                return
            if parts[5] == "input":
                asyncio.run(_apply_input(record["cdp_port"], payload))
                self._json(200, {"status": "accepted"})
                return
            self._json(404, {"detail": "Not found"})
        except (ValueError, TypeError, json.JSONDecodeError):
            self._json(400, {"detail": "Invalid request"})
        except (URLError, TimeoutError):
            self._json(503, {"detail": "Connector control endpoint unavailable"})
        except Exception as exc:
            self._json(502, {"detail": type(exc).__name__})


async def _connect_page(cdp_port: int):
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}", timeout=8000)
    pages = [page for context in browser.contexts for page in context.pages]
    if not pages:
        await browser.close()
        await playwright.stop()
        raise RuntimeError("No browser tab")
    return playwright, browser, pages[-1]


async def _capture_screenshot(cdp_port: int) -> bytes:
    playwright, browser, page = await _connect_page(cdp_port)
    try:
        return await page.screenshot(type="jpeg", quality=68, timeout=10000)
    finally:
        await browser.close()
        await playwright.stop()


async def _apply_input(cdp_port: int, payload: dict) -> None:
    playwright, browser, page = await _connect_page(cdp_port)
    try:
        action = payload.get("action")
        if action == "click":
            viewport = page.viewport_size or {"width": 1280, "height": 800}
            x = max(0, min(int(payload.get("x", 0)), viewport["width"] - 1))
            y = max(0, min(int(payload.get("y", 0)), viewport["height"] - 1))
            await page.mouse.click(x, y)
        elif action == "type":
            await page.keyboard.insert_text(str(payload.get("text") or "")[:2000])
        elif action == "press":
            key = str(payload.get("key") or "")
            allowed = {"Enter", "Tab", "Escape", "Backspace", "Space", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"}
            if key not in allowed:
                raise ValueError("Unsupported key")
            await page.keyboard.press(key)
        elif action == "scroll":
            delta = max(-2000, min(int(payload.get("delta_y", 0)), 2000))
            await page.mouse.wheel(0, delta)
        else:
            raise ValueError("Unsupported input action")
    finally:
        await browser.close()
        await playwright.stop()


def main() -> None:
    parsed = urlsplit(BACKEND_URL)
    if not BACKEND_URL or parsed.scheme not in {"http", "https"} or not parsed.netloc or not AGENT_TOKEN:
        raise SystemExit("Configure SERVER_CONNECTOR_BACKEND_URL and SERVER_CONNECTOR_AGENT_TOKEN.")
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    Thread(target=_poll_forever, name="server-connector-poll", daemon=True).start()
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), AgentHandler)
    server.daemon_threads = True
    print(f"Smart Merchant Windows connector agent listening on {LISTEN_HOST}:{LISTEN_PORT}.", flush=True)
    print("Restrict this port with Windows Firewall; never publish it or Edge CDP ports to the internet.", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        with workers_lock:
            for record in workers.values():
                _terminate_worker(record)
            workers.clear()


if __name__ == "__main__":
    main()
