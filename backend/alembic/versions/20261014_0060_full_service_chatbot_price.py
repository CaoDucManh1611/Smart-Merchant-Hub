"""Set the default Full-Service Chatbot rental price to 3,000,000 VND."""

from decimal import Decimal, InvalidOperation

from alembic import op
import sqlalchemy as sa


revision = "20261014_0060"
down_revision = "20261012_0059"
branch_labels = None
depends_on = None


def _replace_default_price(old_price: int, new_price: int) -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("service_plans"):
        return

    plans = sa.Table("service_plans", sa.MetaData(), autoload_with=bind)
    rows = bind.execute(
        sa.select(plans.c.id, plans.c.features).where(plans.c.code == "pro")
    ).mappings().all()
    for row in rows:
        features = row["features"]
        if not isinstance(features, dict):
            continue
        try:
            current_price = Decimal(str(features.get("chatbot_rental_price")))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if current_price != Decimal(old_price):
            continue
        bind.execute(
            sa.update(plans)
            .where(plans.c.id == row["id"])
            .values(features={**features, "chatbot_rental_price": new_price})
        )


def upgrade() -> None:
    # Preserve admin-set prices; only move the previous default value.
    _replace_default_price(1_500_000, 3_000_000)


def downgrade() -> None:
    _replace_default_price(3_000_000, 1_500_000)
