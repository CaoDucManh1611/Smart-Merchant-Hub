"""Per-shop migration primitives used by the staged SaaS cutover.

The migration is deliberately callback based: the source may be the legacy
database while the destination is a transaction already routed to a shop
schema.  No function in this module chooses a tenant from request data or
deletes a source row.  That makes dry-runs, retries and rollback safe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from typing import Any, Callable, Iterable, Mapping, Sequence


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _canonical_row(row: Mapping[str, Any]) -> str:
    return json.dumps(
        {str(key): value for key, value in sorted(row.items(), key=lambda item: str(item[0]))},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    )


def checksum_rows(rows: Iterable[Mapping[str, Any]]) -> str:
    """Return a stable SHA-256 checksum independent of input row order."""
    canonical = sorted(_canonical_row(row) for row in rows)
    digest = hashlib.sha256()
    for row in canonical:
        digest.update(row.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


@dataclass(frozen=True)
class MigrationReport:
    """Result of copying one deterministic batch/table."""

    table: str | None = None
    rows_copied: int = 0
    cursor: int | None = None
    checksum: str = ""
    dry_run: bool = False
    skipped_rows: int = 0
    errors: tuple[str, ...] = field(default_factory=tuple)


def copy_rows(
    rows: Sequence[Mapping[str, Any]],
    write_row: Callable[[Mapping[str, Any]], Any],
    *,
    cursor: int | None = None,
    dry_run: bool = False,
    table: str | None = None,
) -> MigrationReport:
    """Copy rows with an id cursor, preserving resumability and idempotence.

    Rows must expose an integer ``id``.  The callback is invoked only for rows
    strictly after ``cursor`` and never during a dry-run.
    """
    ordered = sorted(rows, key=lambda row: int(row.get("id", 0)))
    pending: list[Mapping[str, Any]] = []
    skipped = 0
    for row in ordered:
        try:
            row_id = int(row["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Migration rows require an integer id") from exc
        if row_id <= 0:
            raise ValueError("Migration row ids must be positive")
        if cursor is not None and row_id <= int(cursor):
            skipped += 1
            continue
        pending.append(row)

    if not dry_run:
        for row in pending:
            write_row(row)

    return MigrationReport(
        table=table,
        rows_copied=len(pending),
        cursor=int(pending[-1]["id"]) if pending else cursor,
        checksum=checksum_rows(pending),
        dry_run=dry_run,
        skipped_rows=skipped,
    )


@dataclass(frozen=True)
class TableMigrationResult:
    table: str
    source_rows: int
    copied_rows: int
    source_checksum: str
    destination_checksum: str
    cursor: int | None
    dry_run: bool


def migrate_table(
    *,
    table: str,
    source_rows: Sequence[Mapping[str, Any]],
    write_row: Callable[[Mapping[str, Any]], Any],
    cursor: int | None = None,
    dry_run: bool = False,
) -> TableMigrationResult:
    """Copy one table and return checksums suitable for an audit record."""
    report = copy_rows(
        source_rows,
        write_row,
        cursor=cursor,
        dry_run=dry_run,
        table=table,
    )
    copied = [row for row in source_rows if cursor is None or int(row["id"]) > int(cursor)]
    return TableMigrationResult(
        table=table,
        source_rows=len(source_rows),
        copied_rows=report.rows_copied,
        source_checksum=checksum_rows(source_rows),
        destination_checksum=checksum_rows(copied),
        cursor=report.cursor,
        dry_run=dry_run,
    )


def verify_table_counts(
    source_rows: Sequence[Mapping[str, Any]],
    destination_rows: Sequence[Mapping[str, Any]],
) -> bool:
    """Verify both cardinality and content, not just a row count."""
    return len(source_rows) == len(destination_rows) and checksum_rows(source_rows) == checksum_rows(destination_rows)


__all__ = [
    "MigrationReport",
    "TableMigrationResult",
    "checksum_rows",
    "copy_rows",
    "migrate_table",
    "verify_table_counts",
]
