"""Add tenant-scoped support tickets, SLA fields and ticket comments."""

from alembic import op
import sqlalchemy as sa


revision = "20260904_0010"
down_revision = "20260904_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "tickets" not in inspector.get_table_names():
        op.create_table(
            "tickets",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("customer_id", sa.Integer(), nullable=False),
            sa.Column("conversation_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="open"),
            sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal"),
            sa.Column("assigned_user_id", sa.Integer(), nullable=True),
            sa.Column("sla_due_at", sa.DateTime(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["assigned_user_id"], ["users.id"], ondelete="SET NULL"),
        )
        for name, column in (
            ("ix_tickets_business_id", "business_id"),
            ("ix_tickets_customer_id", "customer_id"),
            ("ix_tickets_conversation_id", "conversation_id"),
            ("ix_tickets_status", "status"),
            ("ix_tickets_priority", "priority"),
            ("ix_tickets_assigned_user_id", "assigned_user_id"),
            ("ix_tickets_sla_due_at", "sla_due_at"),
        ):
            op.create_index(name, "tickets", [column])
    if "ticket_comments" not in inspector.get_table_names():
        op.create_table(
            "ticket_comments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("ticket_id", sa.Integer(), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("author_user_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["author_user_id"], ["users.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_ticket_comments_business_id", "ticket_comments", ["business_id"])
        op.create_index("ix_ticket_comments_ticket_id", "ticket_comments", ["ticket_id"])


def downgrade() -> None:
    op.drop_index("ix_ticket_comments_ticket_id", table_name="ticket_comments")
    op.drop_index("ix_ticket_comments_business_id", table_name="ticket_comments")
    op.drop_table("ticket_comments")
    for name in (
        "ix_tickets_sla_due_at",
        "ix_tickets_assigned_user_id",
        "ix_tickets_priority",
        "ix_tickets_status",
        "ix_tickets_conversation_id",
        "ix_tickets_customer_id",
        "ix_tickets_business_id",
    ):
        op.drop_index(name, table_name="tickets")
    op.drop_table("tickets")
