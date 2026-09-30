"""Add the Enterprise tier for shops needing more connection slots."""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0051"
down_revision = "20260922_0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "INSERT INTO service_plans "
        "(code, name, description, price, billing_cycle, max_users, max_channels, "
        "max_documents, max_rag_chunks, max_ai_calls, max_ai_cost, features, status) "
        "VALUES ('enterprise', 'Gói Enterprise', "
        "'Gói mở rộng cho shop cần nhiều tài khoản hoặc hơn 6 suất kết nối.', "
        "1500000, 'monthly', 100, 8, 500, 30000, 75000, 2500, "
        "'{\"onboarding\": true, \"support\": \"dedicated\", "
        "\"display_name\": \"Gói Enterprise\", "
        "\"chatbot_rental_price\": 1500000}'::json, 'active') "
        "ON CONFLICT (code) DO UPDATE SET "
        "name = EXCLUDED.name, description = EXCLUDED.description, "
        "price = EXCLUDED.price, max_users = EXCLUDED.max_users, "
        "max_channels = EXCLUDED.max_channels, max_documents = EXCLUDED.max_documents, "
        "max_rag_chunks = EXCLUDED.max_rag_chunks, max_ai_calls = EXCLUDED.max_ai_calls, "
        "max_ai_cost = EXCLUDED.max_ai_cost, features = EXCLUDED.features, status = 'active'"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE service_plans SET status = 'archived' WHERE code = 'enterprise'"
    ))
