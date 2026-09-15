"""SQLAlchemy engine/session helpers for the SaaS control plane."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


platform_engine = create_engine(settings.platform_database_url, pool_pre_ping=True)
PlatformSessionLocal = sessionmaker(
    bind=platform_engine,
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
