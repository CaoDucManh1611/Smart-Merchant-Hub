"""Make channel account ownership global and add encrypted credentials."""
from alembic import op
import sqlalchemy as sa


revision = "20260903_0005"
down_revision = "20260903_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "access_token_encrypted" in {column["name"] for column in sa.inspect(op.get_bind()).get_columns("channels")}:
        return
    op.add_column("channels", sa.Column("access_token_encrypted", sa.Text(), nullable=True))
    op.create_unique_constraint(
        "uq_channels_type_account_global",
        "channels",
        ["channel_type", "external_account_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_channels_type_account_global", "channels", type_="unique")
    op.drop_column("channels", "access_token_encrypted")
