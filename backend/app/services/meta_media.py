"""Media preparation for Meta Messenger and Instagram attachments."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


META_AUDIO_CONTENT_TYPES = {"audio/aac", "audio/m4a", "audio/mp4", "audio/mpeg", "audio/wav"}
META_AUDIO_SUFFIXES = {".aac", ".m4a", ".mp3", ".mp4", ".wav"}


def normalize_meta_audio_upload(source_path: Path, *, content_type: str) -> tuple[Path, str]:
    """Convert browser WebM/Opus and Ogg recordings to Meta-compatible M4A/AAC."""
    source_path = Path(source_path)
    normalized_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if normalized_type in META_AUDIO_CONTENT_TYPES and source_path.suffix.lower() in META_AUDIO_SUFFIXES:
        return source_path, normalized_type

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("Meta cần voice M4A/AAC; backend chưa có ffmpeg để chuyển đổi bản ghi âm")

    target_path = source_path.with_suffix(".m4a")
    try:
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
                "ipod",
                str(target_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        target_path.unlink(missing_ok=True)
        raise RuntimeError("Chuyển voice sang M4A/AAC quá thời gian cho phép") from exc
    if completed.returncode != 0 or not target_path.is_file() or target_path.stat().st_size == 0:
        target_path.unlink(missing_ok=True)
        raise RuntimeError("Không thể chuyển voice sang M4A/AAC để gửi Facebook/Instagram")
    return target_path, "audio/mp4"
