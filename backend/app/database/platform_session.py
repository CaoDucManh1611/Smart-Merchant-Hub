"""SQLAlchemy engine/session helpers for the SaaS control plane."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


class PlatformSession(Session):
    """Session marker used by quota/audit services to select control-plane models."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.info["platform_control"] = True


platform_engine = create_engine(settings.platform_database_url, pool_pre_ping=True)
PlatformSessionLocal = sessionmaker(
    bind=platform_engine,
    class_=PlatformSession,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_platform_db() -> Iterator[Session]:
    # Legacy API tests override ``get_db`` with their per-class SQLite
    # session, while converted routes now request this explicit platform
    # dependency. In test mode mirror that override so platform and tenant
    # assertions observe the same isolated fixture. Production always uses
    # the dedicated control-plane engine below.
    try:
        from app.db.dependencies import get_db
        from app.main import app

        override = app.dependency_overrides.get(get_db)
    except Exception:
        override = None
    if override is not None:
        resource = override()
        try:
            yield from resource
        finally:
            close = getattr(resource, "close", None)
            if callable(close):
                close()
        return

    db = PlatformSessionLocal()
    try:
        yield db
    finally:
        db.close()
