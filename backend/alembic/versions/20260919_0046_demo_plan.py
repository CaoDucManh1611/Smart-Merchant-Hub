"""Add the zero-cost, no-channel onboarding plan."""

from alembic import op
import sqlalchemy as sa


revision = "20260919_0046"
down_revision = "20260919_0045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "INSERT INTO service_plans "
        "(code, name, description, price, billing_cycle, max_users, max_channels, "
        "max_documents, max_rag_chunks, max_ai_calls, max_ai_cost, features, status) "
        "VALUES ('demo', 'Gói Demo', "
        "'Gói dùng thử 0 đồng để xem giao diện và quy trình CRM. Chưa mở kết nối mạng xã hội.', "
        "0, 'monthly', 1, 0, 0, 0, 50, 0, "
        "'{\"onboarding\": true, \"support\": \"email\", \"display_name\": \"Gói Demo\", \"demo_only\": true}'::json, 'active') "
        "ON CONFLICT (code) DO UPDATE SET "
        "name = EXCLUDED.name, description = EXCLUDED.description, price = EXCLUDED.price, "
        "max_users = EXCLUDED.max_users, max_channels = EXCLUDED.max_channels, "
        "max_documents = EXCLUDED.max_documents, max_rag_chunks = EXCLUDED.max_rag_chunks, "
        "max_ai_calls = EXCLUDED.max_ai_calls, max_ai_cost = EXCLUDED.max_ai_cost, "
        "features = EXCLUDED.features, status = 'active'"
    ))


def downgrade() -> None:
    op.execute(sa.text("UPDATE service_plans SET status = 'archived' WHERE code = 'demo'"))

