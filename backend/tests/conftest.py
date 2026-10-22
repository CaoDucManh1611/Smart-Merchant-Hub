"""Isolated PostgreSQL test bootstrap with SQLite importer fixtures."""

from __future__ import annotations

import importlib.util
import os
import sys
import uuid
import warnings
from pathlib import Path

import pytest
import sqlalchemy
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool


# Never let tests inherit the restored CRM databases. Configure disposable
# PostgreSQL targets before application modules import their global engines.
_TEST_RUNTIME = Path(__file__).parents[1] / ".pytest_tmp"
_TEST_RUNTIME.mkdir(parents=True, exist_ok=True)
# Pytest resolves a relative ``--basetemp`` from the invocation directory,
# which may be either the repository root or ``backend``.
(Path.cwd() / ".pytest_tmp").mkdir(parents=True, exist_ok=True)
_GLOBAL_TEST_DATABASE = _TEST_RUNTIME / "global.db"
_RUN_POSTGRES_TESTS = os.environ.get("RUN_POSTGRES_TESTS", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
_TEST_SCHEMAS: list[tuple[object, str]] = []
_TEST_ENGINES = []
_POSTGRES_TEST_URLS = {}
_TEST_APPLICATION_NAME = ""
_ORIGINAL_CREATE_ENGINE = sqlalchemy.create_engine


def _configured_postgres_urls() -> dict[str, str]:
    """Read runtime URLs without ever reusing their databases for tests."""
    env_file = Path(__file__).parents[1] / ".env"
    file_values = {}
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                file_values[key.strip()] = value.strip().strip("\"'")

    primary = os.environ.get("DATABASE_URL") or file_values.get("DATABASE_URL", "")
    if not primary:
        raise RuntimeError("PostgreSQL tests require DATABASE_URL or backend/.env")
    primary_url = make_url(primary)

    def service_url(name: str, fallback_name: str) -> str:
        configured = os.environ.get(name) or file_values.get(name, "")
        if configured:
            url = make_url(configured)
        else:
            database = primary_url.database or ""
            if "chatbot" not in database:
                return primary_url.render_as_string(hide_password=False)
            url = primary_url.set(database=database.replace("chatbot", fallback_name))
        if not Path("/.dockerenv").exists() and url.host == "db":
            url = url.set(host=os.environ.get("SMART_MERCHANT_TEST_DATABASE_HOST", "127.0.0.1"))
        return url.render_as_string(hide_password=False)

    # A host-side pytest run cannot resolve Compose's `db` hostname. Keep it
    # unchanged inside Docker; on the host, use the published PostgreSQL port.
    if not Path("/.dockerenv").exists() and primary_url.host == "db":
        host = os.environ.get("SMART_MERCHANT_TEST_DATABASE_HOST", "127.0.0.1")
        primary = primary_url.set(host=host).render_as_string(hide_password=False)
        primary_url = make_url(primary)
    return {
        "DATABASE_URL": primary,
        "TENANT_DATABASE_URL": service_url("TENANT_DATABASE_URL", "tenant"),
        "PLATFORM_DATABASE_URL": service_url("PLATFORM_DATABASE_URL", "platform"),
    }


def _prepare_postgres_test_database(url):
    """Create only a dedicated ``*_test`` database when it does not exist."""
    import psycopg
    from psycopg import sql

    source = make_url(url)
    if source.get_backend_name() != "postgresql" or not source.database:
        raise RuntimeError("PostgreSQL tests require PostgreSQL DATABASE_URL, TENANT_DATABASE_URL, and PLATFORM_DATABASE_URL")
    target_name = f"{source.database}_test"
    target = source.set(database=target_name)
    admin_args = {
        "host": source.host,
        "port": source.port or 5432,
        "user": source.username,
        "password": source.password,
        "dbname": "postgres",
    }
    for key in ("sslmode", "sslcert", "sslkey", "sslrootcert", "connect_timeout", "application_name"):
        if key in source.query:
            admin_args[key] = source.query[key]
    try:
        with psycopg.connect(**admin_args, autocommit=True) as connection:
            exists = connection.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (target_name,)
            ).fetchone()
            if not exists:
                connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_name)))
        target_args = dict(admin_args)
        target_args["dbname"] = target_name
        with psycopg.connect(**target_args, autocommit=True) as connection:
            connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except Exception as exc:
        raise RuntimeError(
            f"Cannot prepare isolated PostgreSQL test database {target_name!r} ({type(exc).__name__}). "
            "Use a PostgreSQL role that can create databases, or create the *_test databases first."
        ) from None
    return target


def _create_test_schema(url, schema: str) -> None:
    import psycopg
    from psycopg import sql

    connect_url = make_url(url)
    with psycopg.connect(
        host=connect_url.host,
        port=connect_url.port or 5432,
        user=connect_url.username,
        password=connect_url.password,
        dbname=connect_url.database,
    ) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    _TEST_SCHEMAS.append((connect_url, schema))


def _with_search_path(url, schema: str):
    parsed = make_url(url)
    query = dict(parsed.query)
    query["options"] = f"-csearch_path={schema},public"
    query["application_name"] = _TEST_APPLICATION_NAME
    return parsed.set(query=query)


if _RUN_POSTGRES_TESTS:
    configured_urls = _configured_postgres_urls()
    for key, value in configured_urls.items():
        _POSTGRES_TEST_URLS[key] = _prepare_postgres_test_database(value)

    _run_id = uuid.uuid4().hex[:10]
    _TEST_APPLICATION_NAME = f"smh_pytest_{_run_id}"
    for key, url in _POSTGRES_TEST_URLS.items():
        global_schema = f"pytest_global_{_run_id}_{key.split('_')[0].lower()}"
        _create_test_schema(url, global_schema)
        os.environ[key] = _with_search_path(url, global_schema).render_as_string(hide_password=False)

    _TEST_ENGINE_URL = _POSTGRES_TEST_URLS["DATABASE_URL"].set(
        query={
            **{
                key: value
                for key, value in _POSTGRES_TEST_URLS["DATABASE_URL"].query.items()
                if key != "options"
            },
            "application_name": _TEST_APPLICATION_NAME,
        }
    )

    def _test_create_engine(url, *args, **kwargs):
        nonlocal_schema = None
        try:
            parsed = make_url(url)
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None and parsed.get_backend_name() == "sqlite":
            nonlocal_schema = f"pytest_engine_{_run_id}_{len(_TEST_SCHEMAS):04d}"
            _create_test_schema(_TEST_ENGINE_URL, nonlocal_schema)
            # SQLite-only pool and DBAPI options do not apply to PostgreSQL.
            # Avoid retaining one idle PostgreSQL connection per short-lived
            # in-memory SQLite engine used across the legacy test suite.
            kwargs.pop("connect_args", None)
            kwargs.pop("poolclass", None)
            engine = _ORIGINAL_CREATE_ENGINE(
                _TEST_ENGINE_URL,
                *args,
                connect_args={"options": f"-csearch_path={nonlocal_schema},public"},
                poolclass=NullPool,
                **kwargs,
            )
        else:
            engine = _ORIGINAL_CREATE_ENGINE(url, *args, **kwargs)
        if parsed is not None and parsed.get_backend_name() == "postgresql":
            if parsed.database in {item.database for item in _POSTGRES_TEST_URLS.values()}:
                _TEST_ENGINES.append(engine)
        elif nonlocal_schema:
            _TEST_ENGINES.append(engine)
        return engine

    sqlalchemy.create_engine = _test_create_engine
    sqlalchemy.engine.create.create_engine = _test_create_engine
else:
    os.environ["DATABASE_URL"] = "sqlite:///" + _GLOBAL_TEST_DATABASE.as_posix()
    os.environ["PLATFORM_DATABASE_URL"] = "sqlite:///" + (_TEST_RUNTIME / "platform.db").as_posix()
    os.environ["TENANT_DATABASE_URL"] = "sqlite:///" + (_TEST_RUNTIME / "tenant.db").as_posix()
os.environ["ENVIRONMENT"] = "test"
os.environ["ALLOW_LEGACY_TENANT_HEADER"] = "true"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["RATE_LIMIT_BACKEND"] = "memory"
os.environ["REDIS_URL"] = ""
os.environ["AUTH_LOGIN_RATE_LIMIT_ENABLED"] = "true"
os.environ["AUTH_LOGIN_RATE_LIMIT_REQUESTS"] = "5"
os.environ["AUTH_LOGIN_RATE_LIMIT_WINDOW_SECONDS"] = "180"
os.environ["AUTH_LOGIN_RATE_LIMIT_BACKEND"] = "memory"
os.environ["SECRET_MANAGER_MODE"] = "disabled"
os.environ["OTP_DELIVERY_MODE"] = "disabled"
os.environ["OTP_DELIVERY_FALLBACK"] = "disabled"
os.environ["OTP_FROM_EMAIL"] = ""
os.environ["OTP_SMTP_HOST"] = ""
os.environ["OTP_SMTP_USERNAME"] = ""
os.environ["OTP_SMTP_PASSWORD"] = ""
os.environ["OTP_TWILIO_ACCOUNT_SID"] = ""
os.environ["OTP_TWILIO_AUTH_TOKEN"] = ""
os.environ["OTP_TWILIO_FROM_NUMBER"] = ""
os.environ["CHANNEL_ENCRYPTION_KEY"] = "pytest-channel-encryption-key"
os.environ["CHANNEL_ROUTE_SECRET"] = "test-channel-route-secret-0123456789"
os.environ["RAG_AUTO_REPLY_ENABLED"] = "false"
os.environ["RAG_AUTO_SEED_ENABLED"] = "false"


def _ensure_migration_dependencies() -> None:
    """Make direct ``pytest`` runs find the bundled Alembic runtime.

    Application dependencies are normally installed from requirements.txt.
    The lightweight local test image keeps migration-only packages under
    ``.migrationdeps`` instead, so collection should add that path only when
    Alembic is not already installed in the active interpreter.
    """
    # The repository's migration directory is itself named ``alembic`` but
    # is only a namespace (it has no ``config`` module), so checking the
    # submodule avoids treating that folder as the installed package.
    if importlib.util.find_spec("alembic.config") is not None:
        return
    bundled = Path(__file__).parents[1] / ".migrationdeps"
    if bundled.is_dir():
        sys.path.insert(0, str(bundled))
        # Pytest may have imported the repository's migration directory as an
        # ``alembic`` namespace package before loading this conftest. Remove
        # that placeholder so the real bundled package (with __version__) is
        # imported for the chain test.
        for module_name in list(sys.modules):
            if module_name == "alembic" or module_name.startswith("alembic."):
                del sys.modules[module_name]


_ensure_migration_dependencies()


@pytest.fixture(scope="session", autouse=True)
def _isolated_global_application_database():
    """Provide safe tables for code paths that start a background worker.

    Most tests use their own in-memory database.  A few intentionally exercise
    real application wiring. Their global sessions point to dedicated test
    PostgreSQL databases, never the restored CRM databases.
    """
    import app.models  # noqa: F401 - register every model on Base.metadata
    from app.database.bases import LegacyBase, PlatformBase, TenantBase
    from app.database.session import Base, engine
    from app.database.platform_session import platform_engine
    from app.database.tenant_session import tenant_engine

    # A large part of the legacy test suite still calls
    # ``Business.metadata.create_all`` (the old single-database fixture). The
    # production models now correctly live on two metadata boundaries, so
    # keep those tests meaningful on their isolated test engine. This is
    # test-only compatibility; production migrations remain separated.
    if not getattr(LegacyBase.metadata, "_tenant_fixture_bootstrapped", False):
        legacy_create_all = LegacyBase.metadata.create_all
        LegacyBase.metadata._legacy_create_all = legacy_create_all

        def create_all_with_tenant_tables(bind, tables=None, checkfirst=True, **kwargs):
            legacy_create_all(
                bind,
                tables=tables,
                checkfirst=checkfirst,
                **kwargs,
            )
            PlatformBase.metadata.create_all(bind, checkfirst=checkfirst, **kwargs)
            TenantBase.metadata.create_all(bind, checkfirst=checkfirst, **kwargs)

        LegacyBase.metadata.create_all = create_all_with_tenant_tables
        LegacyBase.metadata._tenant_fixture_bootstrapped = True

    Base.metadata.create_all(engine)
    if _RUN_POSTGRES_TESTS:
        # Preserve the legacy fixture's control-plane availability behavior:
        # converted tests that use the platform engine create their own data,
        # while CRM tenant tables also exist on the dedicated tenant engine.
        TenantBase.metadata.create_all(tenant_engine)
    yield
    for test_engine in (engine, platform_engine, tenant_engine):
        test_engine.dispose()


def pytest_unconfigure(config):
    """Dispose test connections before removing this run's private schemas."""
    for engine in reversed(_TEST_ENGINES):
        try:
            engine.dispose()
        except Exception:
            pass
    if not _RUN_POSTGRES_TESTS:
        return
    import psycopg
    from psycopg import sql

    for url, schema in reversed(_TEST_SCHEMAS):
        try:
            with psycopg.connect(
                host=url.host,
                port=url.port or 5432,
                user=url.username,
                password=url.password,
                dbname=url.database,
                autocommit=True,
            ) as connection:
                connection.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND application_name = %s AND pid <> pg_backend_pid()",
                    (url.database, _TEST_APPLICATION_NAME),
                )
                connection.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
                )
        except Exception as exc:
            warnings.warn(
                f"Could not remove PostgreSQL test schema {schema!r} "
                f"from {url.database!r} ({type(exc).__name__}).",
                stacklevel=1,
            )
