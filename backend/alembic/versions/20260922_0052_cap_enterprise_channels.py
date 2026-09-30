"""Keep every customer-facing package within the six supported channels."""

from alembic import op
import sqlalchemy as sa


revision = "20260922_0052"
down_revision = "20260922_0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text(
        "UPDATE service_plans SET max_channels = 6, "
        "description = 'Gói mở rộng cho shop vận hành đủ 6 nền tảng với hạn mức nhân sự và AI cao hơn.' "
        "WHERE code = 'enterprise'"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "UPDATE service_plans SET max_channels = 8, "
        "description = 'Gói mở rộng cho shop cần nhiều tài khoản hoặc hơn 6 suất kết nối.' "
        "WHERE code = 'enterprise'"
    ))
