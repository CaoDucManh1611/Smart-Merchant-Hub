"""Destructively reset the public schema and recreate the application's 20 tables.

This is intentionally a separate, explicit command. Normal application startup
only performs idempotent create/alter migrations and never deletes user data.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running this file directly from backend/scripts on Windows.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.database.init_db import init_db
from app.database.session import engine


def reset_database() -> None:
    # Drop every user table in public, including legacy tables not represented
    # by the current 20-table model. CASCADE handles foreign-key dependencies.
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                DO $$
                DECLARE
                    table_record RECORD;
                BEGIN
                    FOR table_record IN
                        SELECT tablename
                        FROM pg_tables
                        WHERE schemaname = 'public'
                    LOOP
                        EXECUTE format(
                            'DROP TABLE IF EXISTS public.%I CASCADE',
                            table_record.tablename
                        );
                    END LOOP;
                END $$;
                """
            )
        )

    init_db()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete all public tables and recreate the 20-table schema."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the destructive reset.",
    )
    args = parser.parse_args()

    if not args.yes:
        parser.error("This command deletes all public tables. Re-run with --yes.")

    print("Resetting public schema...")
    reset_database()
    print("Database reset completed. The 20 application tables are ready.")


if __name__ == "__main__":
    main()
