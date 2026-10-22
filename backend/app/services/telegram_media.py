"""Audio normalization required by Telegram's voice-message API."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


TELEGRAM_VOICE_CONTENT_TYPES = {"audio/ogg", "application/ogg", "audio/opus"}


def normalize_telegram_voice_upload(source_path: Path, *, content_type: str) -> tuple[Path, str]:
    """Return an OGG/Opus voice note; convert browser WebM recordings with ffmpeg."""
    source_path = Path(source_path)
    normalized_type = str(content_type or "").strip().lower()
    if source_path.suffix.lower() == ".ogg" and normalized_type in TELEGRAM_VOICE_CONTENT_TYPES:
        return source_path, "audio/ogg"

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("Telegram cần voice OGG/Opus; backend chưa có ffmpeg để chuyển đổi bản ghi âm")

    target_path = source_path.with_suffix(".ogg")
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source_path),
            "-vn",
            "-c:a",
            "libopus",
            "-b:a",
            "48k",
            "-f",
            "ogg",
            str(target_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0 or not target_path.is_file() or target_path.stat().st_size == 0:
        target_path.unlink(missing_ok=True)
        raise RuntimeError("Không thể chuyển bản ghi âm sang OGG/Opus để gửi Telegram")
    return target_path, "audio/ogg"
