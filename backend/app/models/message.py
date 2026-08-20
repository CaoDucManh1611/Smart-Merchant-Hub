from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )

    channel: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
    )

    external_user_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    external_message_id: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
    )

    direction: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="inbound",
        server_default="inbound",
    )

    content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    media_type: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    media_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    raw_payload: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )

    conversation = relationship(
        "Conversation",
        back_populates="messages",
    )
