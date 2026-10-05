"""Small stdlib-only first-run pairing helper for local channel connectors."""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from threading import Event, Thread
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse


_HEARTBEAT_THREADS: set[str] = set()


def history_checkpoint_path(runtime_dir: Path, channel_type: str, connector_token: str) -> Path:
    """Keep resumable import state isolated per paired shop without storing its token."""
    fingerprint = hashlib.sha256(str(connector_token).encode("utf-8")).hexdigest()[:16]
    return runtime_dir / f"{channel_type}-history-{fingerprint}.json"


def post_history_batch(channel_type: str, backend_url: str, connector_token: str, messages: list[dict]) -> tuple[int, str]:
    """Send one bounded historical batch to the automation-free CRM import route."""
    request = Request(
        f"{backend_url.rstrip('/')}/api/channels/{channel_type}/history",
        data=json.dumps({"messages": messages}, ensure_ascii=False).encode("utf-8"),
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


def configure_local_connector(channel_type: str, runtime_dir: Path, package_dir: Path) -> tuple[str, str]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    config_path = runtime_dir / "connector_config.json"
    if config_path.is_file():
        try:
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            backend_url = str(saved.get("backend_url") or "").strip().rstrip("/")
            connector_token = str(saved.get("connector_token") or "").strip()
            if backend_url and connector_token:
                automatic_restart = os.environ.pop("SMART_MERCHANT_AUTO_RESTART", "") == "1"
                answer = "" if automatic_restart else input("Đã có kết nối lưu trên máy này. Nhấn Enter để dùng, hoặc nhập R để ghép nối lại: ").strip().lower()
                if automatic_restart or answer != "r":
                    os.environ[f"{channel_type.upper()}_BACKEND_URL"] = backend_url
                    os.environ[f"{channel_type.upper()}_CONNECTOR_TOKEN"] = connector_token
                    start_connector_heartbeat(channel_type, backend_url, connector_token)
                    return backend_url, connector_token
        except (OSError, ValueError, TypeError):
            pass

    defaults_path = package_dir / "connector_defaults.json"
    try:
        defaults = json.loads(defaults_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        defaults = {}
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

    pairing_code = input("Nhập pairing code trong mục Liên kết mạng xã hội: ").strip()
    if not pairing_code:
        raise SystemExit("Chưa nhập pairing code.")
    request = Request(
        f"{backend_url}/api/channels/pair",
        data=json.dumps({"pairing_code": pairing_code}).encode("utf-8"),
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
