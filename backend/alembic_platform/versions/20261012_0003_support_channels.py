"""Multiple channels in one support ticket; retain legacy provider."""
from alembic import op
import sqlalchemy as sa

revision = '20261012_0003_support_channels'
down_revision = '20261011_0002_support_requests'
branch_labels = None
depends_on = None


def upgrade():
    columns = {
        column['name']
        for column in sa.inspect(op.get_bind()).get_columns('platform_support_requests')
    }
    if 'providers' not in columns:
        op.add_column('platform_support_requests', sa.Column('providers', sa.JSON(), nullable=True))


def downgrade():
    columns = {
        column['name']
        for column in sa.inspect(op.get_bind()).get_columns('platform_support_requests')
    }
    if 'providers' in columns:
        op.drop_column('platform_support_requests', 'providers')
