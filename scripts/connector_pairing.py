"""Small stdlib-only first-run pairing helper for local channel connectors."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse


def configure_local_connector(channel_type: str, runtime_dir: Path, package_dir: Path) -> tuple[str, str]:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    config_path = runtime_dir / "connector_config.json"
    if config_path.is_file():
        try:
            saved = json.loads(config_path.read_text(encoding="utf-8"))
            backend_url = str(saved.get("backend_url") or "").strip().rstrip("/")
            connector_token = str(saved.get("connector_token") or "").strip()
            if backend_url and connector_token:
                answer = input("Đã có kết nối lưu trên máy này. Nhấn Enter để dùng, hoặc nhập R để ghép nối lại: ").strip().lower()
                if answer != "r":
                    os.environ[f"{channel_type.upper()}_BACKEND_URL"] = backend_url
                    os.environ[f"{channel_type.upper()}_CONNECTOR_TOKEN"] = connector_token
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
    print("Đã ghép nối. Mã truy cập được lưu trên máy này; không gửi file cấu hình cho người khác.")
    return backend_url, connector_token
