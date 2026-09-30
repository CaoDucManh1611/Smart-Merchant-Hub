"""Add tenant-owned customer tags for segmentation."""

from alembic import op
import sqlalchemy as sa


revision = "20260904_0012"
down_revision = "20260904_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "customer_tags" in inspector.get_table_names():
        return
    op.create_table(
        "customer_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("customer_id", "tag_id", name="uq_customer_tags_pair"),
    )
    op.create_index("ix_customer_tags_business_id", "customer_tags", ["business_id"])
    op.create_index("ix_customer_tags_customer_id", "customer_tags", ["customer_id"])
    op.create_index("ix_customer_tags_tag_id", "customer_tags", ["tag_id"])
    # Preserve existing conversation labels as customer labels during the
    # transition. Legacy NULL-tenant conversations are intentionally ignored.
    op.execute(sa.text("""
        INSERT INTO customer_tags (business_id, customer_id, tag_id)
        SELECT c.business_id, c.customer_id, ct.tag_id
        FROM conversation_tags ct
        JOIN conversations c ON c.id = ct.conversation_id
        JOIN tags t ON t.id = ct.tag_id AND t.business_id = c.business_id
        WHERE c.business_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM customer_tags existing
              WHERE existing.customer_id = c.customer_id
                AND existing.tag_id = ct.tag_id
          )
    """))


def downgrade() -> None:
    op.drop_index("ix_customer_tags_tag_id", table_name="customer_tags")
    op.drop_index("ix_customer_tags_customer_id", table_name="customer_tags")
    op.drop_index("ix_customer_tags_business_id", table_name="customer_tags")
    op.drop_table("customer_tags")
