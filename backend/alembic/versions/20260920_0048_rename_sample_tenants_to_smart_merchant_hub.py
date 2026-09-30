"""Rename legacy ThienShop sample tenants to the Smart Merchant Hub brand.

Revision ID: 20260920_0048
Revises: 20260920_0047
Create Date: 2026-09-20
"""

from alembic import op
import sqlalchemy as sa


revision = "20260920_0048"
down_revision = "20260920_0047"
branch_labels = None
depends_on = None


TENANT_RENAMES = (
    {
        "old_name": "thienshop",
        "old_slug": "thienshop",
        "new_name": "Smart Merchant Hub",
        "new_slug": "smart-merchant-hub",
    },
    {
        "old_name": "ThienShop",
        "old_slug": "thienshop-2",
        "new_name": "Smart Merchant Hub 2",
        "new_slug": "smart-merchant-hub-2",
    },
    {
        "old_name": "ThienShopshin",
        "old_slug": "thienshopshin",
        "new_name": "Smart Merchant Hub 3",
        "new_slug": "smart-merchant-hub-3",
    },
)


def _rename_tenants(*, reverse: bool) -> None:
    bind = op.get_bind()

    for tenant in TENANT_RENAMES:
        source_name = tenant["new_name"] if reverse else tenant["old_name"]
        source_slug = tenant["new_slug"] if reverse else tenant["old_slug"]
        target_name = tenant["old_name"] if reverse else tenant["new_name"]
        target_slug = tenant["old_slug"] if reverse else tenant["new_slug"]

        bind.execute(
            sa.text(
                "UPDATE businesses "
                "SET name = :target_name, slug = :target_slug "
                "WHERE name = :source_name AND slug = :source_slug"
            ),
            {
                "target_name": target_name,
                "target_slug": target_slug,
                "source_name": source_name,
                "source_slug": source_slug,
            },
        )


def upgrade() -> None:
    _rename_tenants(reverse=False)


def downgrade() -> None:
    _rename_tenants(reverse=True)
