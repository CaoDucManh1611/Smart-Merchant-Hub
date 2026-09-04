"""Bootstrap the current Smart Merchant Hub schema.

This baseline is intentionally metadata-driven because the repository already
contains the canonical SQLAlchemy schema. Future changes must be separate,
explicit Alembic revisions and must not edit this file.
"""
from alembic import op
from sqlalchemy import text

from app.database.session import Base
import app.models  # noqa: F401


revision = "20260903_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    raise RuntimeError("The baseline migration is not reversible; restore a database backup instead.")
