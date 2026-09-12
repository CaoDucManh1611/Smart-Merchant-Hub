"""Align legacy timestamp columns with the ORM nullability contract."""

from alembic import op
import sqlalchemy as sa


revision = "20260912_0040"
down_revision = "20260912_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing rows were checked before this migration and contain no NULL
    # values.  Making these audit/config timestamps NOT NULL removes the
    # recurring Alembic drift reported by ``alembic check``.
    op.alter_column(
        "canned_responses",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
    )
    op.alter_column(
        "canned_responses",
        "updated_at",
        existing_type=sa.DateTime(),
        nullable=False,
    )
    op.alter_column(
        "chatbot_followups",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "chatbot_followups",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=True,
    )
    op.alter_column(
        "canned_responses",
        "updated_at",
        existing_type=sa.DateTime(),
        nullable=True,
    )
    op.alter_column(
        "canned_responses",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=True,
    )
