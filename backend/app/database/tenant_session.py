"""Tenant database sessions with transaction-local schema routing."""

from collections.abc import Iterator
from contextlib import contextmanager
from threading import RLock

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.tenancy.schema import validate_schema_name


tenant_engine = create_engine(settings.tenant_database_url, pool_pre_ping=True)
TenantSessionLocal = sessionmaker(
    bind=tenant_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)

# SQLite's in-memory/static-pool fixtures share one DB-API connection across
# request and background-worker threads. Serialize those compatibility
# sessions so a worker cannot commit while the webhook still has a cursor in
# flight. PostgreSQL sessions never take this lock.
_SQLITE_SESSION_LOCK = RLock()


@contextmanager
def tenant_session(schema_name: str) -> Iterator[Session]:
    """Open one transaction routed only to a validated shop schema."""

    schema = validate_schema_name(schema_name)
    override_resource = None
    db = None
    # Webhook tests keep their isolated per-class SQLite engine behind a
    # ``get_db`` dependency override, while ingress code opens this context
    # manager directly. Reuse that override when present so webhook and API
    # paths exercise the same tenant fixture; production has no overrides and
    # always uses the dedicated tenant engine below.
    try:
        from app.db.dependencies import get_db
        from app.main import app

        override = app.dependency_overrides.get(get_db)
    except Exception:
        override = None
    if override is not None:
        candidate = override()
        try:
            db = next(candidate)
            if db.bind is None or db.bind.dialect.name != "sqlite":
                db = None
                candidate.close()
            else:
                override_resource = candidate
        except Exception:
            close = getattr(candidate, "close", None)
            if callable(close):
                close()
            db = None
    if db is None:
        db = TenantSessionLocal()
    sqlite_lock_acquired = False
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        _SQLITE_SESSION_LOCK.acquire()
        sqlite_lock_acquired = True
    db.info["tenant_schema"] = schema

    def route_transaction(_session, _transaction, connection):
        # CRM services commit more than once. SET LOCAL expires at each
        # commit, so every following transaction must restore the same schema.
        # SQLite-based local tests and lightweight demos do not implement
        # PostgreSQL's search_path/set_config primitives; explicit
        # business_id predicates remain the compatibility boundary there.
        if connection.dialect.name != "postgresql":
            return
        connection.execute(
            text("SELECT set_config('search_path', :search_path, true)"),
            {"search_path": f'"{schema}", public'},
        )

    event.listen(db, "after_begin", route_transaction)
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        if override_resource is not None:
            close = getattr(override_resource, "close", None)
            if callable(close):
                close()
        db.close()
        if sqlite_lock_acquired:
            _SQLITE_SESSION_LOCK.release()
