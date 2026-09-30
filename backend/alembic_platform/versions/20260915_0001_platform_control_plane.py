"""initial SaaS control plane

Revision ID: 20260915_0001
Revises:
"""

from alembic import op

from app.database.bases import PlatformBase
import app.models.platform_control  # noqa: F401
import app.models.channel_route  # noqa: F401


revision = "20260915_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    PlatformBase.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    PlatformBase.metadata.drop_all(bind=op.get_bind())
