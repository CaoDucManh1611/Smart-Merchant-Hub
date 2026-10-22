"""Durable unique payOS orders and recipient snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "20261011_0058"
down_revision = "20261011_0057"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("subscription_payment_attempts"):
        return

    op.create_table(
        "subscription_payment_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("order_code", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("payment_link_id", sa.String(255)),
        sa.Column("qr_code", sa.String(4096)),
        sa.Column("checkout_url", sa.String(2048)),
        sa.Column("bank_name", sa.String(255)),
        sa.Column("bank_bin", sa.String(20)),
        sa.Column("account_name", sa.String(255)),
        sa.Column("account_number", sa.String(100)),
        sa.Column("reference", sa.String(255)),
        sa.Column("provider_transaction_reference", sa.String(255)),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("reconciliation_required", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("subscription_id", name="uq_subscription_payment_attempt_subscription"),
        sa.UniqueConstraint("order_code", name="uq_subscription_payment_attempt_order"),
        sa.UniqueConstraint("payment_link_id", name="uq_subscription_payment_attempt_link"),
        sa.CheckConstraint("amount > 0", name="ck_subscription_payment_amount_positive"),
    )


def downgrade():
    if sa.inspect(op.get_bind()).has_table("subscription_payment_attempts"):
        op.drop_table("subscription_payment_attempts")
