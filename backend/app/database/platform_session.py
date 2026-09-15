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
    db = PlatformSessionLocal()
    try:
        yield db
    finally:
        db.close()
