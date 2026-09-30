from app.database.platform_session import get_platform_db
from app.db.database import SessionLocal


def get_legacy_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


# Compatibility alias for routes that have not yet been converted to
# tenant_session. New control-plane code must request get_platform_db.
get_db = get_legacy_db


__all__ = ["get_db", "get_legacy_db", "get_platform_db"]
