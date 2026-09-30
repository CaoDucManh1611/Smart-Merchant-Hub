"""Add append-only ticket handling history events."""

from alembic import op
import sqlalchemy as sa


revision = "20260904_0013"
down_revision = "20260904_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "ticket_events" in inspector.get_table_names():
        return
    op.create_table(
        "ticket_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("from_value", sa.Text(), nullable=True),
        sa.Column("to_value", sa.Text(), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_ticket_events_business_id", "ticket_events", ["business_id"])
    op.create_index("ix_ticket_events_ticket_id", "ticket_events", ["ticket_id"])
    op.create_index("ix_ticket_events_event_type", "ticket_events", ["event_type"])
    op.create_index("ix_ticket_events_created_at", "ticket_events", ["created_at"])
    op.execute(sa.text("""
        INSERT INTO ticket_events (business_id, ticket_id, event_type, to_value, created_at)
        SELECT t.business_id, t.id, 'created', t.status, t.created_at
        FROM tickets t
        WHERE NOT EXISTS (
            SELECT 1 FROM ticket_events e
            WHERE e.ticket_id = t.id AND e.business_id = t.business_id
        )
    """))


def downgrade() -> None:
    op.drop_index("ix_ticket_events_created_at", table_name="ticket_events")
    op.drop_index("ix_ticket_events_event_type", table_name="ticket_events")
    op.drop_index("ix_ticket_events_ticket_id", table_name="ticket_events")
    op.drop_index("ix_ticket_events_business_id", table_name="ticket_events")
    op.drop_table("ticket_events")
