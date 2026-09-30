"""Remove legacy global channel tokens after encrypted migration is verified.

Dry-run is the default. ``--confirm`` is required because deleting these rows
is irreversible without a database backup. The command prints key names and
counts only, never credential values.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database.session import SessionLocal
from app.models.channel import Channel
from app.models.setting import AppSetting


LEGACY_TOKEN_KEYS = ("meta.facebook_page_access_token", "meta.instagram_access_token")


def main() -> int:
    parser = argparse.ArgumentParser(description="Retire legacy app_settings channel credentials")
    parser.add_argument("--confirm", action="store_true", help="actually delete the legacy rows")
    args = parser.parse_args()

    with SessionLocal() as db:
        rows = db.scalars(select(AppSetting).where(AppSetting.key.in_(LEGACY_TOKEN_KEYS))).all()
        encrypted_channels = db.scalars(
            select(Channel).where(Channel.access_token_encrypted.is_not(None))
        ).all()
        print(f"Legacy credential rows found: {len(rows)}")
        print(f"Encrypted channel credentials available: {len(encrypted_channels)}")
        if not rows:
            print("Nothing to retire.")
            return 0
        if not encrypted_channels:
            print("Refusing to delete: no encrypted channel credential was found.")
            return 2
        if not args.confirm:
            print("Dry-run only. Re-run with --confirm after a verified PostgreSQL backup.")
            return 0
        for row in rows:
            db.delete(row)
        db.commit()
        print(f"Deleted {len(rows)} legacy credential row(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

