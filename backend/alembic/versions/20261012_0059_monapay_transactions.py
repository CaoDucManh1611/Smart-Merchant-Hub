"""Store verified MONA Pay incoming transactions with a unique provider code."""

from alembic import op
import sqlalchemy as sa


revision = "20261012_0059"
down_revision = "20261011_0058"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("monapay_incoming_transactions"):
        return

    op.create_table(
        "monapay_incoming_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transaction_code", sa.String(100), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False, server_default=""),
        sa.Column("transfer_date", sa.String(40), nullable=False),
        sa.Column("bank_name", sa.String(100), nullable=False),
        sa.Column("transaction_type", sa.String(20), nullable=False),
        sa.Column("is_sandbox", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("received_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("transaction_code", name="uq_monapay_transaction_code"),
    )


def downgrade():
    if sa.inspect(op.get_bind()).has_table("monapay_incoming_transactions"):
        op.drop_table("monapay_incoming_transactions")
