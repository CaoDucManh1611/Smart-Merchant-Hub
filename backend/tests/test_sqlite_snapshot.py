import sqlite3

import pytest

from app.scripts.sqlite_snapshot import create_sqlite_snapshot, validate_sqlite_snapshot


def test_sqlite_snapshot_is_consistent_and_does_not_overwrite_source(tmp_path):
    source = tmp_path / "live.sqlite"
    backup = tmp_path / "backups" / "snapshot.sqlite"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        db.execute("INSERT INTO customers VALUES (1, 'Alice')")

    manifest = create_sqlite_snapshot(source, backup)

    assert manifest["table_count"] == 1
    assert len(str(manifest["sha256"])) == 64
    with sqlite3.connect(f"{backup.as_uri()}?mode=ro", uri=True) as db:
        assert db.execute("SELECT * FROM customers").fetchall() == [(1, "Alice")]
    with pytest.raises(FileExistsError):
        create_sqlite_snapshot(source, backup)
    assert validate_sqlite_snapshot(backup)["sha256"] == manifest["sha256"]


def test_sqlite_source_must_be_snapshotted_during_dry_run_before_cutover(tmp_path, monkeypatch):
    from app.scripts import migrate_tenant

    source = tmp_path / "legacy.sqlite"
    source.touch()
    backup = tmp_path / "snapshot.sqlite"
    monkeypatch.setattr("sys.argv", [
        "migrate_tenant", "42", "--sqlite-source", str(source), "--sqlite-backup", str(backup),
        "--cutover", "--operation-id", "pilot-42",
    ])

    with pytest.raises(SystemExit) as error:
        migrate_tenant.main()

    assert error.value.code == 2
    assert not backup.exists()
