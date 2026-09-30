"""Alembic runner for independently versioned shop schemas."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, text

from app.tenancy.schema import validate_schema_name


BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG_PATH = BACKEND_DIR / "alembic-tenant.ini"


def _config(connection: Connection, schema_name: str) -> Config:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    config.attributes["connection"] = connection
    config.attributes["tenant_schema"] = validate_schema_name(schema_name)
    return config


def current_tenant_revision(connection: Connection, schema_name: str) -> str | None:
    schema = validate_schema_name(schema_name)
    exists = connection.execute(
        text("SELECT 1 FROM information_schema.tables WHERE table_schema=:schema AND table_name='alembic_version'"),
        {"schema": schema},
    ).scalar_one_or_none()
    if not exists:
        return None
    return connection.execute(text(f'SELECT version_num FROM "{schema}".alembic_version')).scalar_one_or_none()


def upgrade_tenant_schema(
    connection: Connection,
    schema_name: str,
    revision: str = "head",
) -> str:
    schema = validate_schema_name(schema_name)
    # pgvector is installed per database, while every shop schema shares the
    # tenant database. Enable it before the template creates embedding columns.
    connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    command.upgrade(_config(connection, schema), revision)
    current = current_tenant_revision(connection, schema)
    if current is None:
        raise RuntimeError(f"tenant migration did not record a revision for {schema}")
    return current
