"""Tenant database sessions with transaction-local schema routing."""

from collections.abc import Iterator
from contextlib import contextmanager

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


@contextmanager
def tenant_session(schema_name: str) -> Iterator[Session]:
    """Open one transaction routed only to a validated shop schema."""

    schema = validate_schema_name(schema_name)
    db = TenantSessionLocal()
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
        db.close()
