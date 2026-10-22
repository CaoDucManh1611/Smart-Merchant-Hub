"""Separate platform staff permissions from shop roles."""
from alembic import op
import sqlalchemy as sa

revision = '20261020_0061'
down_revision = '20261014_0060'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('platform_memberships', sa.Column('platform_role', sa.String(30), nullable=False, server_default='owner'))
    op.add_column('platform_memberships', sa.Column('platform_permissions', sa.JSON(), nullable=True))
    op.create_table('platform_staff_audit',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('actor_id', sa.Integer(), nullable=False),
        sa.Column('subject_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(40), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()))


def downgrade():
    op.drop_table('platform_staff_audit')
    op.drop_column('platform_memberships', 'platform_permissions')
    op.drop_column('platform_memberships', 'platform_role')
