"""Multiple channels in one support ticket; retain legacy provider."""
from alembic import op
import sqlalchemy as sa

revision = '20261012_0003_support_channels'
down_revision = '20261011_0002_support_requests'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('platform_support_requests', sa.Column('providers', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('platform_support_requests', 'providers')
