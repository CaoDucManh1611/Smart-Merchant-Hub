"""Cross-process maintenance barrier shared by HTTP, workers and backups."""

import os
import time
from contextlib import contextmanager
from pathlib import Path

from starlette.responses import JSONResponse

from app.core.config import settings


class MaintenanceBusy(RuntimeError):
    pass


def backup_root() -> Path:
    root = Path(settings.BACKUP_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def lock_file(name: str, *, shared: bool = False, timeout: float = 0):
    stream = (backup_root() / name).open("a+b")
    stream.seek(0, os.SEEK_END)
    if stream.tell() == 0:
        stream.write(b"0")
        stream.flush()
    deadline = time.monotonic() + timeout
    while True:
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBRLCK if shared else msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
            return stream
        except (BlockingIOError, OSError):
            if time.monotonic() >= deadline:
                stream.close()
                raise MaintenanceBusy("Hệ thống đang sao lưu hoặc khôi phục. Vui lòng thử lại sau.") from None
            time.sleep(0.1)


def release_lock(stream):
    try:
        if os.name == "nt":
            import msvcrt
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_UN)
    finally:
        stream.close()


@contextmanager
def application_access():
    if (backup_root() / "maintenance.json").exists():
        raise MaintenanceBusy("Hệ thống đang sao lưu hoặc khôi phục.")
    stream = lock_file("application.lock", shared=True)
    try:
        # Close the race with a backup starting between the first check and lock.
        if (backup_root() / "maintenance.json").exists():
            raise MaintenanceBusy("Hệ thống đang sao lưu hoặc khôi phục.")
        yield
    finally:
        release_lock(stream)


class BackupMaintenanceMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/") or path.startswith("/api/platform/backups"):
            return await self.app(scope, receive, send)
        try:
            with application_access():
                # Hold through streaming and FastAPI background tasks, not just headers.
                await self.app(scope, receive, send)
        except MaintenanceBusy:
            response = JSONResponse(
                {"detail": "Hệ thống đang sao lưu hoặc khôi phục. Vui lòng thử lại sau."},
                status_code=503, headers={"Retry-After": "10"},
            )
            await response(scope, receive, send)
