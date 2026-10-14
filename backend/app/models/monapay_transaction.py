"""Verified incoming transactions received from MONA Pay."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class MonaIncomingTransaction(Base):
    __tablename__ = "monapay_incoming_transactions"
    __table_args__ = (UniqueConstraint("transaction_code", name="uq_monapay_transaction_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_code: Mapped[str] = mapped_column(String(100), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    transfer_date: Mapped[str] = mapped_column(String(40), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(100), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_sandbox: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
