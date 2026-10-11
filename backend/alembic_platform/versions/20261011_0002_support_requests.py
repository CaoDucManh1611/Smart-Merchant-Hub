"""Shop connection support ledger and durable update history."""
from alembic import op
import sqlalchemy as sa

revision = '20261011_0002_support_requests'
down_revision = '20260922_0014'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('platform_support_requests',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('business_id', sa.Integer(), sa.ForeignKey('platform_businesses.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), nullable=False),
        sa.Column('idempotency_key', sa.String(180), nullable=False),
        sa.Column('request_fingerprint', sa.String(64), nullable=False),
        sa.Column('provider', sa.String(30), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('response', sa.Text(), nullable=True),
        sa.Column('assigned_admin_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('business_id', 'idempotency_key', name='uq_support_requests_business_key'),
        sa.CheckConstraint("status IN ('open','in_progress','resolved','closed')", name='ck_support_requests_status'),
        sa.CheckConstraint("provider IN ('facebook','instagram','telegram','zalo','tiktok','shopee')", name='ck_support_requests_provider'),
    )
    op.create_index('ix_platform_support_requests_business_id', 'platform_support_requests', ['business_id'])
    op.create_table('platform_support_request_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('request_id', sa.Integer(), sa.ForeignKey('platform_support_requests.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), nullable=False),
        sa.Column('from_status', sa.String(30), nullable=True),
        sa.Column('to_status', sa.String(30), nullable=False),
        sa.Column('response', sa.Text(), nullable=True),
        sa.Column('assigned_admin_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_platform_support_request_history_request_id', 'platform_support_request_history', ['request_id'])


def downgrade():
    op.drop_table('platform_support_request_history')
    op.drop_table('platform_support_requests')
