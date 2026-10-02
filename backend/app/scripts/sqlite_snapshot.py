"""Create/validate a consistent, immutable SQLite migration snapshot."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path


def _readonly_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=30)


def validate_sqlite_snapshot(path: Path) -> dict[str, object]:
    snapshot = Path(path).resolve(strict=True)
    with closing(_readonly_connection(snapshot)) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise ValueError("SQLite backup failed integrity_check.")
        tables = db.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        if not tables:
            raise ValueError("SQLite source has no application tables.")
        page_count = int(db.execute("PRAGMA page_count").fetchone()[0])
    digest = hashlib.sha256()
    with snapshot.open("rb") as backup_file:
        for chunk in iter(lambda: backup_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(snapshot),
        "sha256": digest.hexdigest(),
        "table_count": int(tables),
        "page_count": page_count,
        "size_bytes": snapshot.stat().st_size,
    }


def create_sqlite_snapshot(source_path: Path, backup_path: Path) -> dict[str, object]:
    source = Path(source_path).resolve(strict=True)
    backup = Path(backup_path).resolve(strict=False)
    if source == backup:
        raise ValueError("SQLite backup path must differ from the source.")
    if backup.exists():
        raise FileExistsError(f"Refusing to overwrite SQLite backup: {backup}")
    backup.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the exact destination atomically; never replace an existing file.
    with backup.open("xb"):
        pass
    try:
        with closing(_readonly_connection(source)) as source_db, closing(sqlite3.connect(backup, timeout=30)) as backup_db:
            source_db.backup(backup_db)
        return validate_sqlite_snapshot(backup)
    except Exception:
        backup.unlink(missing_ok=True)
        raise
