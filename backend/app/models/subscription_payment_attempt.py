"""One durable provider order per subscription request."""
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class SubscriptionPaymentAttempt(Base):
    __tablename__ = "subscription_payment_attempts"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_subscription_payment_amount_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id", ondelete="RESTRICT"), unique=True)
    order_code: Mapped[int] = mapped_column(BigInteger, unique=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="VND")
    status: Mapped[str] = mapped_column(String(30), default="creating")
    payment_link_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    qr_code: Mapped[str | None] = mapped_column(String(4096))
    checkout_url: Mapped[str | None] = mapped_column(String(2048))
    bank_name: Mapped[str | None] = mapped_column(String(255))
    bank_bin: Mapped[str | None] = mapped_column(String(20))
    account_name: Mapped[str | None] = mapped_column(String(255))
    account_number: Mapped[str | None] = mapped_column(String(100))
    reference: Mapped[str | None] = mapped_column(String(255))
    provider_transaction_reference: Mapped[str | None] = mapped_column(String(255))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reconciliation_required: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
