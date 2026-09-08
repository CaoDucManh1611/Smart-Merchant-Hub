"""Add structured customer contact and consent collection tables."""

from alembic import op
import sqlalchemy as sa


revision = "20260908_0032"
down_revision = "20260907_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("value_encrypted", sa.Text(), nullable=False),
        sa.Column("value_hash", sa.String(length=64), nullable=False),
        sa.Column("masked_value", sa.String(length=255), nullable=False),
        sa.Column("verification_status", sa.String(length=20), nullable=False, server_default="unverified"),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="manual"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("business_id", "kind", "value_hash", name="uq_customer_contact_business_kind_hash"),
    )
    op.create_index("ix_customer_contacts_business_id", "customer_contacts", ["business_id"])
    op.create_index("ix_customer_contacts_customer_id", "customer_contacts", ["customer_id"])
    op.create_index("ix_customer_contacts_kind", "customer_contacts", ["kind"])
    op.create_index("ix_customer_contacts_value_hash", "customer_contacts", ["value_hash"])
    op.create_index("ix_customer_contacts_verification_status", "customer_contacts", ["verification_status"])

    op.create_table(
        "customer_addresses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_name", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("address_line1", sa.String(length=255), nullable=False),
        sa.Column("address_line2", sa.String(length=255), nullable=True),
        sa.Column("ward", sa.String(length=120), nullable=True),
        sa.Column("district", sa.String(length=120), nullable=True),
        sa.Column("province", sa.String(length=120), nullable=True),
        sa.Column("postal_code", sa.String(length=20), nullable=True),
        sa.Column("country", sa.String(length=80), nullable=False, server_default="VN"),
        sa.Column("verification_status", sa.String(length=20), nullable=False, server_default="unverified"),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="manual"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_customer_addresses_business_id", "customer_addresses", ["business_id"])
    op.create_index("ix_customer_addresses_customer_id", "customer_addresses", ["customer_id"])

    op.create_table(
        "customer_collection_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("purpose", sa.String(length=40), nullable=False, server_default="order"),
        sa.Column("required_fields", sa.JSON(), nullable=False),
        sa.Column("collected_fields", sa.JSON(), nullable=False),
        sa.Column("current_field", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("source_channel", sa.String(length=30), nullable=True),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_customer_collection_sessions_business_id", "customer_collection_sessions", ["business_id"])
    op.create_index("ix_customer_collection_sessions_customer_id", "customer_collection_sessions", ["customer_id"])
    op.create_index("ix_customer_collection_sessions_conversation_id", "customer_collection_sessions", ["conversation_id"])
    op.create_index("ix_customer_collection_sessions_status", "customer_collection_sessions", ["status"])

    op.create_table(
        "customer_verification_challenges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("customer_contacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("requested_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_customer_verification_challenges_business_id", "customer_verification_challenges", ["business_id"])
    op.create_index("ix_customer_verification_challenges_customer_id", "customer_verification_challenges", ["customer_id"])
    op.create_index("ix_customer_verification_challenges_contact_id", "customer_verification_challenges", ["contact_id"])
    op.create_index("ix_customer_verification_challenges_status", "customer_verification_challenges", ["status"])

    op.create_table(
        "customer_consents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_id", sa.Integer(), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_channel", sa.String(length=30), nullable=True),
        sa.Column("policy_version", sa.String(length=40), nullable=True),
        sa.Column("evidence_message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("granted_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_customer_consents_business_id", "customer_consents", ["business_id"])
    op.create_index("ix_customer_consents_customer_id", "customer_consents", ["customer_id"])
    op.create_index("ix_customer_consents_purpose", "customer_consents", ["purpose"])
    op.create_index("ix_customer_consents_status", "customer_consents", ["status"])
    op.create_index("ix_customer_consents_evidence_message_id", "customer_consents", ["evidence_message_id"])


def downgrade() -> None:
    op.drop_table("customer_consents")
    op.drop_table("customer_verification_challenges")
    op.drop_table("customer_collection_sessions")
    op.drop_table("customer_addresses")
    op.drop_table("customer_contacts")
