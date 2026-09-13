"""Test bootstrap for the repository's optional migration runtime."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest


# Never let a local test run inherit Docker's ``db`` hostname or the restored
# CRM database.  The environment must be set before test modules import the
# global application engine.
_TEST_RUNTIME = Path(__file__).parents[1] / ".pytest_tmp"
_TEST_RUNTIME.mkdir(parents=True, exist_ok=True)
# Pytest resolves a relative ``--basetemp`` from the invocation directory,
# which may be either the repository root or ``backend``.
(Path.cwd() / ".pytest_tmp").mkdir(parents=True, exist_ok=True)
_GLOBAL_TEST_DATABASE = _TEST_RUNTIME / "global.db"
os.environ["DATABASE_URL"] = "sqlite:///" + _GLOBAL_TEST_DATABASE.as_posix()
os.environ["ENVIRONMENT"] = "test"
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["RATE_LIMIT_BACKEND"] = "memory"
os.environ["REDIS_URL"] = ""
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
    the real application wiring and may outlive the request thread, so their
    global session must point to an isolated SQLite database rather than the
    restored PostgreSQL instance.
    """
    import app.models  # noqa: F401 - register every model on Base.metadata
    from app.database.session import Base, engine

    Base.metadata.create_all(engine)
    yield
    engine.dispose()
