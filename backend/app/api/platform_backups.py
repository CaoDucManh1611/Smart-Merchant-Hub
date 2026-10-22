"""Platform-admin-only backup operations. Restore never runs in the request."""

import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.passwords import verify_password
from app.auth.platform import require_platform_admin
from app.core.config import settings
from app.db.dependencies import get_db
from app.models.business import User
from app.services import platform_backup as service
from app.services.backup_maintenance import MaintenanceBusy, backup_root

router = APIRouter(prefix="/platform/backups", dependencies=[Depends(require_platform_admin)])


class RestoreConfirmation(BaseModel):
    confirmation: str = Field(max_length=40)
    password: str = Field(min_length=1, max_length=256)


def _enqueue(tasks: BackgroundTasks, kind: str, actor: User, backup_id: str | None = None):
    try:
        job, mutex = service.start_job(kind, actor.id, backup_id)
    except MaintenanceBusy as error:
        raise HTTPException(409, str(error)) from None
    except service.BackupError as error:
        raise HTTPException(400, str(error)) from None
    tasks.add_task(service.run_job, job, mutex)
    return job


@router.get("")
def list_archives():
    return service.list_backups()


@router.post("", status_code=202)
def create_backup(tasks: BackgroundTasks, actor: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    db.close()
    return _enqueue(tasks, "create", actor)


@router.get("/jobs/{job_id}")
def job_status(job_id: str):
    try:
        return service.read_job(job_id)
    except service.BackupError as error:
        raise HTTPException(404, str(error)) from None


@router.post("/import", status_code=201)
async def import_backup(file: UploadFile):
    size = 0
    with tempfile.NamedTemporaryFile(dir=backup_root(), suffix=".upload", delete=False) as stream:
        path = Path(stream.name)
        try:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.BACKUP_MAX_BYTES:
                    raise HTTPException(413, "Tệp sao lưu quá lớn.")
                stream.write(chunk)
            stream.close()
            manifest = service.validate_archive(path)
            target = backup_root() / f"{manifest['id']}.zip"
            if not target.exists():
                path.replace(target)
            service._json_write(backup_root() / f"{manifest['id']}.manifest.json", manifest)
            return {"id": manifest["id"], "created_at": manifest["created_at"]}
        except service.BackupError as error:
            raise HTTPException(400, str(error)) from None
        finally:
            stream.close()
            path.unlink(missing_ok=True)
            await file.close()


@router.get("/{backup_id}/download")
def download_backup(backup_id: str):
    try:
        path = service.archive_path(backup_id)
    except service.BackupError as error:
        raise HTTPException(404, str(error)) from None
    return FileResponse(path, media_type="application/zip", filename=f"smart-merchant-{backup_id}.zip", headers={"Cache-Control": "no-store"})


@router.post("/{backup_id}/verify", status_code=202)
def verify_backup(backup_id: str, tasks: BackgroundTasks, actor: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    db.close()
    return _enqueue(tasks, "verify", actor, backup_id)


@router.post("/{backup_id}/restore", status_code=202)
def restore_backup(backup_id: str, payload: RestoreConfirmation, tasks: BackgroundTasks, actor: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    if payload.confirmation != "KHÔI PHỤC":
        raise HTTPException(422, "Hãy nhập chính xác KHÔI PHỤC để xác nhận.")
    if not verify_password(payload.password, actor.password_hash):
        raise HTTPException(403, "Mật khẩu quản trị không đúng.")
    # Auth SELECTs must not keep ACCESS SHARE locks while pg_restore performs DDL.
    db.close()
    return _enqueue(tasks, "restore", actor, backup_id)
