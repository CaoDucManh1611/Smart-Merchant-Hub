import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zipfile import ZipFile

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.api.platform_backups import router
from app.auth.passwords import hash_password
from app.auth.platform import require_platform_admin
from app.services import platform_backup as backup
from app.services.backup_maintenance import BackupMaintenanceMiddleware, MaintenanceBusy, application_access, backup_root, lock_file, release_lock


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setattr(backup.settings, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(backup.settings, "AUTH_SECRET", "test-signing-key-" * 4)
    monkeypatch.setattr(backup, "UPLOAD_ROOT", tmp_path / "uploads")
    backup.UPLOAD_ROOT.mkdir()
    (backup.UPLOAD_ROOT / "photo.jpg").write_bytes(b"photo")
    (tmp_path / ".env").write_text("PRIVATE_API_KEY=do-not-backup")
    monkeypatch.setattr(backup, "targets", lambda: {"legacy": make_url("postgresql+psycopg://admin:sensitive-db-password@db/test")})
    metadata = {"schemas": ["public"], "counts": {"public.users": 1}, "revisions": {"public": ["v1"]}, "server_major": 16}
    monkeypatch.setattr(backup, "_metadata", lambda _: metadata)
    monkeypatch.setattr(backup, "capabilities", lambda: {"available": True, "reason": None})

    def command(tool, url, *args):
        if tool == "pg_dump":
            Path(next(arg.removeprefix("--file=") for arg in args if str(arg).startswith("--file="))).write_bytes(b"native-dump")

    monkeypatch.setattr(backup, "_command", command)
    monkeypatch.setattr(backup, "_verify_dump", Mock())
    return tmp_path


def test_archive_roundtrip_checksums_and_no_environment_secrets(environment):
    manifest = backup.create_archive(7)
    path = backup.archive_path(manifest["id"])
    assert backup.validate_archive(path) == manifest
    with ZipFile(path) as archive:
        assert set(archive.namelist()) == {"databases/legacy.dump", "uploads/photo.jpg", "manifest.json"}
        assert b"sensitive-db-password" not in archive.read("manifest.json")
        assert b"do-not-backup" not in archive.read("manifest.json")
    assert backup.list_backups()["items"][0]["file_count"] == 1


def rewrite(path, manifest, payload):
    with ZipFile(path, "w") as archive:
        for name, value in payload.items():
            archive.writestr(name, value)
        archive.writestr("manifest.json", json.dumps(manifest))


def test_modified_file_or_manifest_is_rejected(environment):
    manifest = backup.create_archive(7)
    path = backup.archive_path(manifest["id"])
    rewrite(path, manifest, {"databases/legacy.dump": b"native-dump", "uploads/photo.jpg": b"other"})
    with pytest.raises(backup.BackupError, match="checksum"):
        backup.validate_archive(path)
    manifest["created_by"] = 99
    rewrite(path, manifest, {"databases/legacy.dump": b"native-dump", "uploads/photo.jpg": b"photo"})
    with pytest.raises(backup.BackupError, match="ký"):
        backup.validate_archive(path)


def test_traversal_and_duplicate_names_are_rejected_even_if_signed(environment):
    manifest = backup.create_archive(7)
    path = backup.archive_path(manifest["id"])
    manifest["files"]["uploads/../../outside"] = manifest["files"].pop("uploads/photo.jpg")
    manifest["signature"] = backup._signature(manifest)
    rewrite(path, manifest, {"databases/legacy.dump": b"native-dump", "uploads/../../outside": b"photo"})
    with pytest.raises(backup.BackupError, match="đường dẫn"):
        backup.validate_archive(path)
    assert not (environment / "outside").exists()
    with pytest.raises(backup.BackupError):
        backup.archive_path("../../.env")


def test_only_one_job_can_run_and_application_gate_blocks_writes(environment):
    job, mutex = backup.start_job("create", 7)
    try:
        with pytest.raises(MaintenanceBusy):
            backup.start_job("create", 7)
        with application_access():
            with pytest.raises(MaintenanceBusy):
                lock_file("application.lock")
    finally:
        release_lock(mutex)
    backup.recover_interrupted_jobs()
    assert backup.read_job(job["id"])["status"] == "failed"


def test_restore_verifies_and_creates_safety_backup_before_apply(environment, monkeypatch):
    manifest = backup.create_archive(7)
    steps = []
    original = backup.create_archive

    def safety(*args, **kwargs):
        steps.append("safety")
        return original(*args, **kwargs)

    monkeypatch.setattr(backup, "create_archive", safety)
    monkeypatch.setattr(backup, "_verify_dump", lambda *_: steps.append("verify"))
    monkeypatch.setattr(backup, "_apply", lambda *_: steps.append("apply"))
    job, mutex = backup.start_job("restore", 7, manifest["id"])
    backup.run_job(job, mutex)
    assert steps == ["verify", "safety", "apply"]
    result = backup.read_job(job["id"])
    assert result["status"] == "succeeded"
    assert backup.archive_path(result["safety_backup_id"]).exists()
    assert not (backup_root() / "maintenance.json").exists()


def test_failed_restore_rolls_back_and_failed_rollback_keeps_maintenance(environment, monkeypatch):
    manifest = backup.create_archive(7)
    apply = Mock(side_effect=[RuntimeError("failed restore"), None])
    monkeypatch.setattr(backup, "_apply", apply)
    job, mutex = backup.start_job("restore", 7, manifest["id"])
    backup.run_job(job, mutex)
    assert apply.call_count == 2
    assert backup.read_job(job["id"])["status"] == "failed"
    assert not (backup_root() / "maintenance.json").exists()
    monkeypatch.setattr(backup, "_apply", Mock(side_effect=RuntimeError("failed both")))
    job, mutex = backup.start_job("restore", 7, manifest["id"])
    backup.run_job(job, mutex)
    assert backup.read_job(job["id"])["maintenance_required"] is True
    assert (backup_root() / "maintenance.json").exists()


def test_http_returns_retryable_maintenance_without_running_endpoint(environment):
    app = FastAPI()
    app.add_middleware(BackupMaintenanceMiddleware)
    endpoint = Mock(return_value={"ok": True})

    @app.get("/api/test")
    def route():
        return endpoint()

    (backup_root() / "maintenance.json").write_text('{}')
    response = TestClient(app).get("/api/test")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "10"
    endpoint.assert_not_called()


def test_interrupted_restore_cannot_be_cleared_by_unrelated_or_failed_job(environment, monkeypatch):
    manifest = backup.create_archive(7)
    flag = backup_root() / "maintenance.json"
    flag.write_text(json.dumps({"kind": "restore", "job_id": "f" * 32}))
    with pytest.raises(backup.BackupError, match="bảo trì"):
        backup.start_job("verify", 7, manifest["id"])
    monkeypatch.setattr(backup, "_verify_dump", Mock(side_effect=backup.BackupError("verify failed")))
    job, mutex = backup.start_job("restore", 7, manifest["id"])
    backup.run_job(job, mutex)
    assert backup.read_job(job["id"])["maintenance_required"] is True
    assert flag.exists()


def test_all_routes_are_platform_admin_only_and_restore_requires_password(environment, monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def denied():
        raise HTTPException(403, "admin required")

    app.dependency_overrides[require_platform_admin] = denied
    client = TestClient(app)
    for method, url in [("GET", ""), ("POST", ""), ("GET", "/bad/download"), ("POST", "/bad/verify"), ("POST", "/bad/restore")]:
        assert client.request(method, "/api/platform/backups" + url, json={"confirmation": "KHÔI PHỤC", "password": "wrong"}).status_code == 403
    app.dependency_overrides[require_platform_admin] = lambda: SimpleNamespace(id=7, password_hash=hash_password("admin-test-password"))
    start = Mock(return_value=({"id": "a" * 32, "status": "running"}, object()))
    monkeypatch.setattr(backup, "start_job", start)
    monkeypatch.setattr(backup, "run_job", Mock())
    url = "/api/platform/backups/" + "b" * 32 + "/restore"
    assert client.post(url, json={"confirmation": "no", "password": "admin-test-password"}).status_code == 422
    assert client.post(url, json={"confirmation": "KHÔI PHỤC", "password": "wrong"}).status_code == 403
    start.assert_not_called()
    response = client.post(url, json={"confirmation": "KHÔI PHỤC", "password": "admin-test-password"})
    assert response.status_code == 202
    assert "password" not in response.text
