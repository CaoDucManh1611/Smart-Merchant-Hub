"""Database session compatibility exports.

Keep one SQLAlchemy engine/session factory for the API and database setup.
"""

from app.database.session import SessionLocal, engine

__all__ = ["SessionLocal", "engine"]
