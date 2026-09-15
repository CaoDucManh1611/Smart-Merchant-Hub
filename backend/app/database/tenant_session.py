"""Tenant database sessions with transaction-local schema routing."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
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
    try:
        with db.begin():
            db.execute(
                text("SELECT set_config('search_path', :search_path, true)"),
                {"search_path": f'"{schema}", public'},
            )
            yield db
    finally:
        db.close()
