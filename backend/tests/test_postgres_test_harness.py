import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool


def test_in_memory_fixture_engines_are_postgres_and_schema_isolated():
    first = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    second = create_engine("sqlite://")
    expected_dialect = (
        "sqlite"
        if os.environ.get("RUN_POSTGRES_TESTS", "1").strip().lower() in {"0", "false", "no"}
        else "postgresql"
    )
    try:
        assert first.dialect.name == second.dialect.name == expected_dialect
        with first.begin() as connection:
            connection.execute(text("CREATE TABLE harness_isolation_probe (id INTEGER PRIMARY KEY)"))
        assert inspect(first).has_table("harness_isolation_probe")
        assert not inspect(second).has_table("harness_isolation_probe")
    finally:
        first.dispose()
        second.dispose()
