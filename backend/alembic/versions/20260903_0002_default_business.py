"""Seed the built-in tenant used by the single-business deployment."""
from alembic import op
from sqlalchemy import text


revision = "20260903_0002"
down_revision = "20260903_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(
        text(
            """
            INSERT INTO businesses (name, slug, status)
            VALUES ('Default Business', 'default-business', 'active')
            ON CONFLICT (slug) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    # Keep tenant data on downgrade; deleting a business is a destructive
    # operation and must be an explicit administrative action.
    pass
