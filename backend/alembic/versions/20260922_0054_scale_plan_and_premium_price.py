"""Restore the four-channel Scale tier and update Premium pricing."""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0054"
down_revision = "20260922_0053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "INSERT INTO service_plans "
        "(code, name, description, price, billing_cycle, max_users, max_channels, "
        "max_documents, max_rag_chunks, max_ai_calls, max_ai_cost, features, status) "
        "VALUES ('scale', 'Gói Scale', "
        "'Gói cho shop vận hành đồng thời trên 4 nền tảng.', "
        "1000000, 'monthly', 25, 4, 100, 5000, 12000, 500, "
        "'{\"onboarding\": true, \"support\": \"priority\", "
        "\"display_name\": \"Gói Scale\", "
        "\"chatbot_rental_price\": 1000000}'::json, 'active') "
        "ON CONFLICT (code) DO UPDATE SET "
        "name = EXCLUDED.name, description = EXCLUDED.description, "
        "price = EXCLUDED.price, max_users = EXCLUDED.max_users, "
        "max_channels = EXCLUDED.max_channels, max_documents = EXCLUDED.max_documents, "
        "max_rag_chunks = EXCLUDED.max_rag_chunks, max_ai_calls = EXCLUDED.max_ai_calls, "
        "max_ai_cost = EXCLUDED.max_ai_cost, features = EXCLUDED.features, status = 'active'"
    ))
    op.execute(sa.text(
        "UPDATE service_plans SET price = 1500000, max_ai_cost = 1500, "
        "description = 'Gói đầy đủ cho shop vận hành đủ 6 nền tảng.', "
        "features = jsonb_set(COALESCE(features::jsonb, '{}'::jsonb), "
        "'{chatbot_rental_price}', '1500000'::jsonb, true)::json "
        "WHERE code = 'pro'"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE service_plans SET price = 1000000, max_ai_cost = 1000, "
        "features = jsonb_set(COALESCE(features::jsonb, '{}'::jsonb), "
        "'{chatbot_rental_price}', '1000000'::jsonb, true)::json "
        "WHERE code = 'pro'"
    ))
    op.execute(sa.text(
        "UPDATE service_plans SET status = 'archived' WHERE code = 'scale'"
    ))
