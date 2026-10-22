"""Exercise native backup/verify/restore only against a newly-created test database."""

import json
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.services import platform_backup as backup
from app.services.backup_maintenance import backup_root


def main():
    source_url = next(iter(backup.targets().values()))
    name = "smh_backup_test_" + uuid4().hex
    admin = create_engine(source_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    created = False
    try:
        with admin.connect() as db:
            db.exec_driver_sql(f'CREATE DATABASE "{name}"')
            created = True
        url = source_url.set(database=name)
        engine = create_engine(url)
        with engine.begin() as db:
            db.exec_driver_sql("CREATE EXTENSION vector")
            db.exec_driver_sql("CREATE TABLE public.alembic_version(version_num varchar(32) PRIMARY KEY)")
            db.exec_driver_sql("INSERT INTO public.alembic_version VALUES ('backup_test_v1')")
            db.exec_driver_sql("CREATE TABLE public.sample_data(id int PRIMARY KEY, body text)")
            db.exec_driver_sql("INSERT INTO public.sample_data VALUES (1,'original')")
            db.exec_driver_sql("CREATE TABLE public.auth_sessions(id int PRIMARY KEY)")
            db.exec_driver_sql("INSERT INTO public.auth_sessions VALUES (1)")
            db.exec_driver_sql("CREATE SCHEMA shop_123")
            db.exec_driver_sql("CREATE TABLE shop_123.embeddings(id int PRIMARY KEY, embedding vector(3))")
            db.exec_driver_sql("INSERT INTO shop_123.embeddings VALUES (1,'[1,2,3]')")
        with tempfile.TemporaryDirectory(dir=backup_root(), prefix="native-check-") as work:
            # Only this disposable DB/uploads path is ever a restore target.
            settings.BACKUP_DIR = str(Path(work) / "archives")
            backup.UPLOAD_ROOT = Path(work) / "uploads"
            backup.UPLOAD_ROOT.mkdir()
            (backup.UPLOAD_ROOT / "sample.txt").write_text("original", encoding="utf-8")
            backup.targets = lambda: {"legacy": url}
            job, mutex = backup.start_job("create", 0)
            backup.run_job(job, mutex)
            assert job["status"] == "succeeded", job
            original_id = job["backup_id"]
            with engine.begin() as db:
                db.exec_driver_sql("INSERT INTO public.sample_data VALUES (2,'newer')")
                db.exec_driver_sql("CREATE SCHEMA shop_999")
                db.exec_driver_sql("CREATE TABLE shop_999.extra(id int)")
            (backup.UPLOAD_ROOT / "sample.txt").write_text("newer", encoding="utf-8")
            (backup.UPLOAD_ROOT / "extra.txt").write_text("extra", encoding="utf-8")
            job, mutex = backup.start_job("restore", 0, original_id)
            backup.run_job(job, mutex)
            assert job["status"] == "succeeded", job
            with engine.connect() as db:
                assert db.scalar(text("SELECT count(*) FROM public.sample_data")) == 1
                assert db.scalar(text("SELECT count(*) FROM public.auth_sessions")) == 0
                assert db.scalar(text("SELECT embedding::text FROM shop_123.embeddings")) == "[1,2,3]"
                assert not db.scalar(text("SELECT count(*) FROM information_schema.schemata WHERE schema_name='shop_999'"))
            assert (backup.UPLOAD_ROOT / "sample.txt").read_text(encoding="utf-8") == "original"
            assert not (backup.UPLOAD_ROOT / "extra.txt").exists()
            assert backup.archive_path(job["safety_backup_id"]).exists()
            print(json.dumps({"isolated_native_restore": "passed", "vectors": "preserved", "uploads": "restored", "old_sessions": "not_reactivated", "live_databases_modified": False}))
        engine.dispose()
    finally:
        if created:
            with admin.connect() as db:
                db.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


if __name__ == "__main__":
    main()
