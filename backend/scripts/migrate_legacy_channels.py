"""Migrate legacy global channel credentials with explicit tenant mapping.

Example:
    python scripts/migrate_legacy_channels.py --mapping channel-map.json --report migration-report.json
"""

import argparse
import json
from pathlib import Path

from app.core.config import settings
from app.database.session import SessionLocal
from app.services.legacy_channel_migration import migrate_legacy_channels


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=Path("channel-migration-report.json"))
    parser.add_argument("--disable-global", action="store_true")
    args = parser.parse_args()

    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
    if not settings.CHANNEL_ENCRYPTION_KEY:
        raise SystemExit("CHANNEL_ENCRYPTION_KEY is required")
    with SessionLocal() as db:
        report = migrate_legacy_channels(
            db, mapping={str(key): int(value) for key, value in mapping.items()},
            encryption_key=settings.CHANNEL_ENCRYPTION_KEY,
        )
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

    if args.disable_global:
        if report["skipped"]:
            raise SystemExit("Refusing to disable global credentials while migration has skipped items")
        print("Migration verified structurally; disable legacy app_settings manually after production smoke test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
