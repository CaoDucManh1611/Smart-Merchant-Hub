"""Media preparation helpers for Zalo Bot outbound messages."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ZALO_AAC_CONTENT_TYPES = {"audio/aac", "audio/x-aac"}


def normalize_zalo_audio_upload(
    source_path: Path,
    *,
    content_type: str,
) -> tuple[Path, str]:
    """Return an AAC/ADTS file because Zalo ``sendVoice`` requires ``.aac``.

    Browsers normally record microphone input as WebM/Opus or Ogg/Opus.  Zalo
    Bot accepts voice URLs only when they point to an AAC file, so non-AAC
    uploads are transcoded before the public URL is handed to Zalo.
    """
    source_path = Path(source_path)
    normalized_content_type = str(content_type or "").strip().lower()
    if source_path.suffix.lower() == ".aac" and normalized_content_type in ZALO_AAC_CONTENT_TYPES:
        return source_path, "audio/aac"

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "Zalo yêu cầu audio .aac; backend chưa có ffmpeg để chuyển đổi file ghi âm"
        )

    target_path = source_path.with_suffix(".aac")
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
            "aac",
            "-b:a",
            "96k",
            "-f",
            "adts",
            str(target_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0 or not target_path.is_file() or target_path.stat().st_size == 0:
        target_path.unlink(missing_ok=True)
        raise RuntimeError("Không thể chuyển audio sang AAC để gửi qua Zalo")
    return target_path, "audio/aac"
