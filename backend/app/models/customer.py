from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class Customer(Base):
    __tablename__ = "customers"

    __table_args__ = (
        UniqueConstraint(
            "channel",
            "external_user_id",
            name="uq_customers_channel_user",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    channel: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    external_user_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )

    conversations = relationship(
        "Conversation",
        back_populates="customer",
        cascade="all, delete-orphan",
    )