from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.database.bases import LegacyBase


# Compatibility aliases. Existing CRM models continue using LegacyBase until
# their repositories are moved to tenant_session in the routing workstream.
Base = LegacyBase


engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)
