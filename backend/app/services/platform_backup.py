"""Signed PostgreSQL/uploads archives, with isolated verification and rollback.

    No shell, Docker socket or database credentials are put in an archive.
    Jobs live outside the databases being restored.
"""

import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from uuid import uuid4
from zipfile import ZipFile, ZIP_STORED, BadZipFile

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.core.config import settings
from app.services.backup_maintenance import backup_root, lock_file, release_lock, MaintenanceBusy

logger = logging.getLogger(__name__)
UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "uploads"
FORMAT = "smart-merchant-backup-v1"


class BackupError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json_write(path: Path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", value):
        raise BackupError("Mã bản sao không hợp lệ.")
    return value


def archive_path(backup_id: str) -> Path:
    path = backup_root() / f"{_identifier(backup_id)}.zip"
    if not path.is_file() or path.is_symlink():
        raise BackupError("Không tìm thấy bản sao lưu.")
    return path


def targets():
    result, seen = {}, set()
    for name, value in (("legacy", settings.DATABASE_URL), ("tenant", settings.tenant_database_url), ("platform", settings.platform_database_url)):
        url = make_url(value)
        if url.get_backend_name() != "postgresql":
            raise BackupError("Sao lưu admin yêu cầu PostgreSQL.")
        identity = (url.host, url.port or 5432, url.database)
        if identity not in seen:
            result[name] = url
            seen.add(identity)
    return result


def capabilities():
    try:
        targets()
        if max(len(settings.AUTH_SECRET), len(settings.CHANNEL_ENCRYPTION_KEY)) < 32:
            raise BackupError("Cần cấu hình khóa mã hóa/ký đủ mạnh trước khi sao lưu.")
        if not all(shutil.which(tool) for tool in ("pg_dump", "pg_restore")):
            raise BackupError("Máy chủ chưa có PostgreSQL client. Hãy cập nhật image backend.")
        return {"available": True, "reason": None}
    except (ValueError, TypeError, ArgumentError) as error:
        return {"available": False, "reason": str(error) if isinstance(error, BackupError) else "Cấu hình database chưa hợp lệ."}


def _signature(manifest: dict) -> str:
    source = manifest.get("signature_key") or ("channel_encryption" if len(settings.CHANNEL_ENCRYPTION_KEY) >= 32 else "auth")
    secret = {"channel_encryption": settings.CHANNEL_ENCRYPTION_KEY, "auth": settings.AUTH_SECRET}.get(source, "")
    if len(secret) < 32:
        raise BackupError("Thiếu khóa ký bản sao lưu.")
    body = json.dumps({key: value for key, value in manifest.items() if key != "signature"}, sort_keys=True, separators=(",", ":")).encode()
    key = hmac.new(secret.encode(), b"smart-merchant-backup-v1", hashlib.sha256).digest()
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def _sha(stream) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _transient_table(name: str) -> bool:
    return name.endswith("_challenges") or name in {
        "auth_sessions", "platform_auth_sessions", "customer_collection_sessions", "crm_jobs", "oauth_states",
    }


def _metadata(url):
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as db:
            schemas = db.execute(text("SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT LIKE 'pg_%' AND schema_name <> 'information_schema' ORDER BY schema_name")).scalars().all()
            tables = db.execute(text("SELECT table_schema, table_name FROM information_schema.tables WHERE table_type='BASE TABLE' AND table_schema NOT LIKE 'pg_%' AND table_schema <> 'information_schema' ORDER BY table_schema, table_name")).all()
            counts, revisions = {}, {}
            quote = engine.dialect.identifier_preparer.quote
            for schema, name in tables:
                qualified = f"{quote(schema)}.{quote(name)}"
                counts[f"{schema}.{name}"] = 0 if _transient_table(name) else int(db.scalar(text(f"SELECT count(*) FROM {qualified}")))
                if name == "alembic_version":
                    revisions[schema] = sorted(db.execute(text(f"SELECT version_num FROM {qualified}")).scalars())
            return {"schemas": schemas, "counts": counts, "revisions": revisions,
                    "server_major": int(db.scalar(text("SHOW server_version_num"))) // 10000}
    finally:
        engine.dispose()


def _command(tool: str, url, *args):
    environment = os.environ.copy()
    environment["PGPASSWORD"] = url.password or ""
    environment["PGCONNECT_TIMEOUT"] = "10"
    environment["PGOPTIONS"] = "-c lock_timeout=30000 -c statement_timeout=1200000"
    for key in ("sslmode", "sslrootcert", "sslcert", "sslkey"):
        if key in url.query:
            environment["PG" + key.upper()] = str(url.query[key])
    command = [tool, "--no-password", "--host", url.host or "localhost", "--port", str(url.port or 5432),
               "--username", url.username or "postgres", "--dbname", url.database, *map(str, args)]
    try:
        result = subprocess.run(command, env=environment, capture_output=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired):
        raise BackupError("Công cụ PostgreSQL không chạy được hoặc đã hết thời gian chờ.") from None
    if result.returncode:
        # Native errors can contain connection details. Do not return/store stderr.
        raise BackupError(f"{tool} thất bại. Kiểm tra quyền database, phiên bản PostgreSQL và dung lượng máy chủ.")


def _restore_dump(url, path: Path, *, clean: bool):
    arguments = ["--no-owner", "--no-privileges", "--single-transaction", "--exit-on-error"]
    if clean:
        arguments += ["--clean", "--if-exists"]
    _command("pg_restore", url, *arguments, path)


def _verify_dump(url, path: Path, expected: dict):
    name = "smh_verify_" + uuid4().hex
    engine = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    created = False
    try:
        with engine.connect() as db:
            db.exec_driver_sql(f'CREATE DATABASE "{name}"')
            created = True
        temporary = url.set(database=name)
        _restore_dump(temporary, path, clean=False)
        if _metadata(temporary) != expected:
            raise BackupError("Database kiểm chứng không khớp số bản ghi hoặc phiên bản của bản sao.")
    finally:
        if created:
            with engine.connect() as db:
                db.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        engine.dispose()


def create_archive(actor_id: int, *, label: str = "manual") -> dict:
    backup_id = uuid4().hex
    manifest = {"format": FORMAT, "id": backup_id, "created_at": _now(), "created_by": actor_id,
                "label": label, "databases": {}, "files": {},
                "signature_key": "channel_encryption" if len(settings.CHANNEL_ENCRYPTION_KEY) >= 32 else "auth"}
    with tempfile.TemporaryDirectory(dir=backup_root(), prefix="snapshot-") as work:
        destination = Path(work) / "archive.zip"
        with ZipFile(destination, "w", compression=ZIP_STORED) as archive:
            for alias, url in targets().items():
                metadata = _metadata(url)
                dump = Path(work) / f"{alias}.dump"
                exclude = [f"--exclude-table-data={name}" for name in metadata["counts"] if _transient_table(name.rsplit(".", 1)[-1])]
                _command("pg_dump", url, "--format=custom", "--no-owner", "--no-privileges", f"--file={dump}", *exclude)
                name = f"databases/{alias}.dump"
                archive.write(dump, name)
                with dump.open("rb") as stream:
                    manifest["files"][name] = {"size": dump.stat().st_size, "sha256": _sha(stream)}
                manifest["databases"][alias] = metadata
            root = UPLOAD_ROOT.resolve()
            if root.exists():
                for file in sorted(root.rglob("*")):
                    if file.is_symlink() or not file.resolve().is_relative_to(root):
                        raise BackupError("Thư mục tải lên chứa liên kết ngoài; không thể sao lưu an toàn.")
                    if not file.is_file():
                        continue
                    name = "uploads/" + file.relative_to(root).as_posix()
                    archive.write(file, name)
                    with file.open("rb") as stream:
                        manifest["files"][name] = {"size": file.stat().st_size, "sha256": _sha(stream)}
            manifest["signature"] = _signature(manifest)
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        if destination.stat().st_size > settings.BACKUP_MAX_BYTES:
            raise BackupError("Bản sao vượt giới hạn dung lượng BACKUP_MAX_BYTES.")
        destination.replace(backup_root() / f"{backup_id}.zip")
    _json_write(backup_root() / f"{backup_id}.manifest.json", manifest)
    return manifest


def validate_archive(path: Path) -> dict:
    try:
        if path.stat().st_size > settings.BACKUP_MAX_BYTES:
            raise BackupError("Tệp sao lưu vượt giới hạn dung lượng.")
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 100000 or sum(item.file_size for item in entries) > settings.BACKUP_MAX_BYTES * 4:
                raise BackupError("Tệp giải nén vượt giới hạn cho phép.")
            if archive.getinfo("manifest.json").file_size > 1024 * 1024:
                raise BackupError("Manifest quá lớn.")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format") != FORMAT or not hmac.compare_digest(str(manifest.get("signature", "")), _signature(manifest)):
                raise BackupError("Bản sao không do hệ thống này ký hoặc đã bị thay đổi. Cần giữ nguyên khóa mã hóa/ký khi chuyển máy.")
            _identifier(manifest["id"])
            if set(manifest["databases"]) != set(targets()):
                raise BackupError("Bố cục database của bản sao không khớp hệ thống hiện tại.")
            allowed_dumps = {f"databases/{alias}.dump" for alias in manifest["databases"]}
            names = [item.filename for item in entries]
            if len(set(names)) != len(names) or set(names) != {"manifest.json", *manifest["files"]}:
                raise BackupError("Danh sách tệp trong bản sao không hợp lệ.")
            if not allowed_dumps.issubset(manifest["files"]):
                raise BackupError("Bản sao thiếu database.")
            for name, expected in manifest["files"].items():
                parts = PurePosixPath(name)
                if "\\" in name or parts.is_absolute() or any(part in {".", ".."} for part in parts.parts) or not (name in allowed_dumps or name.startswith("uploads/")):
                    raise BackupError("Bản sao chứa đường dẫn không hợp lệ.")
                info = archive.getinfo(name)
                if info.is_dir() or info.file_size != expected["size"] or (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise BackupError("Tệp trong bản sao không hợp lệ.")
                with archive.open(name) as stream:
                    if not hmac.compare_digest(_sha(stream), expected["sha256"]):
                        raise BackupError("Tệp sao lưu sai checksum.")
            return manifest
    except BackupError:
        raise
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, BadZipFile, AttributeError):
        raise BackupError("Không đọc được tệp sao lưu hoặc manifest.") from None


def _unpack(path: Path, destination: Path, manifest: dict):
    # Never extractall: signed entries are still constrained to this staging root.
    with ZipFile(path) as archive:
        for name in manifest["files"]:
            target = destination / name
            if not target.resolve().is_relative_to(destination.resolve()):
                raise BackupError("Đường dẫn nằm ngoài thư mục khôi phục.")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _sync_uploads(staging: Path):
    root = UPLOAD_ROOT.resolve()
    root.mkdir(parents=True, exist_ok=True)
    staged = staging / "uploads"
    wanted = {file.relative_to(staged) for file in staged.rglob("*") if file.is_file()} if staged.exists() else set()
    for file in root.rglob("*"):
        if file.is_symlink() or not file.resolve().is_relative_to(root):
            raise BackupError("Tệp tải lên chứa liên kết ngoài.")
        if file.is_file() and file.relative_to(root) not in wanted:
            file.unlink()
    for relative in wanted:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(staged / relative, destination)


def _apply(staging: Path, manifest: dict):
    for alias, url in targets().items():
        _restore_dump(url, staging / "databases" / f"{alias}.dump", clean=True)
        current = _metadata(url)
        extras = set(current["schemas"]) - set(manifest["databases"][alias]["schemas"])
        if extras:
            engine = create_engine(url)
            try:
                with engine.begin() as db:
                    for schema in extras:
                        db.exec_driver_sql(f"DROP SCHEMA {engine.dialect.identifier_preparer.quote(schema)} CASCADE")
            finally:
                engine.dispose()
        if _metadata(url) != manifest["databases"][alias]:
            raise BackupError("Dữ liệu khôi phục không khớp bản sao.")
    _sync_uploads(staging)


def read_job(job_id: str) -> dict:
    path = backup_root() / f"{_identifier(job_id)}.job.json"
    if not path.is_file():
        raise BackupError("Không tìm thấy tác vụ.")
    return json.loads(path.read_text(encoding="utf-8"))


def recover_interrupted_jobs():
    """A lost process releases its OS lock. Interrupted restore stays fail-closed."""
    try:
        mutex = lock_file("job.lock")
    except MaintenanceBusy:
        return
    try:
        flag = backup_root() / "maintenance.json"
        state = json.loads(flag.read_text(encoding="utf-8")) if flag.exists() else {}
        restoring = state.get("kind") == "restore"
        for file in backup_root().glob("*.job.json"):
            data = json.loads(file.read_text(encoding="utf-8"))
            if data.get("status") == "running":
                data.update(status="failed", error="Ứng dụng đã khởi động lại trong lúc xử lý.", maintenance_required=restoring)
                _json_write(file, data)
        if not restoring:
            flag.unlink(missing_ok=True)
    finally:
        release_lock(mutex)


def start_job(kind: str, actor_id: int, backup_id: str | None = None):
    capability = capabilities()
    if not capability["available"]:
        raise BackupError(capability["reason"])
    if kind not in {"create", "verify", "restore"}:
        raise BackupError("Loại tác vụ không hợp lệ.")
    if (backup_root() / "maintenance.json").exists() and kind != "restore":
        raise BackupError("Hệ thống vẫn đang bảo trì. Cần hoàn tất khôi phục trước khi chạy tác vụ khác.")
    if kind != "create":
        archive_path(backup_id or "")
    mutex = lock_file("job.lock")
    try:
        job = {"id": uuid4().hex, "kind": kind, "actor_id": actor_id, "backup_id": backup_id,
               "status": "running", "stage": "Chờ các tác vụ đang chạy kết thúc", "created_at": _now(), "error": None}
        _json_write(backup_root() / f"{job['id']}.job.json", job)
        return job, mutex
    except Exception:
        release_lock(mutex)
        raise


def run_job(job: dict, mutex):
    gate = None
    flag = backup_root() / "maintenance.json"
    safe = not flag.exists()
    job_path = backup_root() / f"{job['id']}.job.json"

    def stage(message):
        job["stage"] = message
        _json_write(job_path, job)

    try:
        _json_write(flag, {"job_id": job["id"], "kind": job["kind"]})
        gate = lock_file("application.lock", timeout=120)
        if job["kind"] == "create":
            stage("Đang sao lưu database và tệp tải lên")
            manifest = create_archive(job["actor_id"])
            job["backup_id"] = manifest["id"]
        else:
            path = archive_path(job["backup_id"])
            stage("Kiểm tra chữ ký và toàn vẹn tệp")
            manifest = validate_archive(path)
            with tempfile.TemporaryDirectory(dir=backup_root(), prefix="restore-") as directory:
                staging = Path(directory)
                _unpack(path, staging, manifest)
                stage("Khôi phục thử vào database tạm và đối chiếu số bản ghi")
                for alias, url in targets().items():
                    expected = manifest["databases"][alias]
                    current = _metadata(url)
                    incompatible = any(
                        schema in current["revisions"] and revision != current["revisions"][schema]
                        for schema, revision in expected["revisions"].items()
                    )
                    if current["server_major"] != expected["server_major"] or incompatible:
                        raise BackupError("Phiên bản PostgreSQL hoặc migration không khớp bản sao.")
                    _verify_dump(url, staging / "databases" / f"{alias}.dump", expected)
                if job["kind"] == "restore":
                    stage("Tạo bản sao an toàn trước khi khôi phục")
                    safety = create_archive(job["actor_id"], label="before_restore")
                    job["safety_backup_id"] = safety["id"]
                    stage("Đang khôi phục database và tệp tải lên")
                    safe = False
                    try:
                        _apply(staging, manifest)
                        safe = True
                    except Exception:
                        stage("Khôi phục gặp lỗi; đang trả lại trạng thái trước thao tác")
                        with tempfile.TemporaryDirectory(dir=backup_root(), prefix="rollback-") as rollback:
                            previous = Path(rollback)
                            _unpack(archive_path(safety["id"]), previous, safety)
                            _apply(previous, safety)
                        safe = True
                        raise BackupError("Khôi phục thất bại; hệ thống đã được trả lại trạng thái trước thao tác.") from None
            job["verified_at"] = _now()
        job.update(status="succeeded", stage="Hoàn tất", completed_at=_now())
    except Exception as error:
        logger.error("Backup task %s failed: %s", job["id"], type(error).__name__)
        message = str(error) if isinstance(error, (BackupError, MaintenanceBusy)) else "Tác vụ thất bại. Kiểm tra quyền database và dung lượng máy chủ."
        job.update(status="failed", error=message, completed_at=_now(), maintenance_required=not safe)
    finally:
        _json_write(job_path, job)
        if safe:
            flag.unlink(missing_ok=True)
        if gate is not None:
            release_lock(gate)
        release_lock(mutex)


def list_backups() -> dict:
    recover_interrupted_jobs()
    rows = []
    for file in backup_root().glob("*.manifest.json"):
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            path = archive_path(data["id"])
            rows.append({key: data[key] for key in ("id", "created_at", "created_by", "label")}
                        | {"size": path.stat().st_size, "database_count": len(data["databases"]), "file_count": sum(name.startswith("uploads/") for name in data["files"])})
        except (OSError, ValueError, KeyError):
            continue
    jobs = []
    for file in sorted(backup_root().glob("*.job.json"), key=lambda path: path.stat().st_mtime, reverse=True)[:20]:
        jobs.append(json.loads(file.read_text(encoding="utf-8")))
    return {**capabilities(), "items": sorted(rows, key=lambda row: row["created_at"], reverse=True), "jobs": jobs,
            "maintenance": (backup_root() / "maintenance.json").exists()}
