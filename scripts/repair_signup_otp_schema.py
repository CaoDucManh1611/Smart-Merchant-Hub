"""Replay the existing additive OTP migration when a legacy DB has schema drift.

Run inside the backend container with PYTHONPATH=/app:
python /app/root-scripts/repair_signup_otp_schema.py
Does not change migration stamps or remove existing records.
"""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from app.db.database import engine


def repair(connection, migration_path):
    spec = importlib.util.spec_from_file_location("signup_schema_repair", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    before = connection.execute(text("SELECT count(*) FROM signup_email_challenges")).scalar_one()
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
    columns = {item["name"] for item in inspect(connection).get_columns("signup_email_challenges")}
    assert {"purpose", "business_id", "role"} <= columns
    assert connection.execute(text("SELECT count(*) FROM signup_email_challenges")).scalar_one() == before
    return before


if __name__ == "__main__":
    path = Path("/app/alembic/versions/20260922_0049_team_email_challenges.py")
    with engine.begin() as connection:
        count = repair(connection, path)
    print(f"OTP schema repaired; {count} existing challenges preserved.")
