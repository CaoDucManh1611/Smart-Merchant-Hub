"""Add tenant-scoped cross-channel customer identities."""
from alembic import op
import sqlalchemy as sa


revision = "20260903_0003"
down_revision = "20260903_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "customer_identities" in inspector.get_table_names():
        return
    op.create_table(
        "customer_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=30), nullable=False),
        sa.Column("external_account_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("external_user_id", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "business_id", "channel", "external_account_id", "external_user_id",
            name="uq_customer_identity_business_channel_account_user",
        ),
    )
    op.create_index("ix_customer_identities_business_id", "customer_identities", ["business_id"])
    op.create_index("ix_customer_identities_customer_id", "customer_identities", ["customer_id"])

    # Preserve existing webhook identities when upgrading a legacy database.
    op.execute(
        sa.text(
            """
            INSERT INTO customer_identities
                (business_id, customer_id, channel, external_account_id, external_user_id)
            SELECT business_id, id, channel, '', external_user_id
            FROM customers
            WHERE business_id IS NOT NULL
            ON CONFLICT (business_id, channel, external_account_id, external_user_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_customer_identities_customer_id", table_name="customer_identities")
    op.drop_index("ix_customer_identities_business_id", table_name="customer_identities")
    op.drop_table("customer_identities")
