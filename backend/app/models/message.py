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

    sender_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="customer",
        server_default="customer",
    )

    sender_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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

    # Deterministic key for a bot response produced from one inbound message.
    # It is separate from the provider's message id because providers return
    # that id only after delivery and may return different ids on retries.
    auto_reply_key: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        nullable=True,
        index=True,
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

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="received",
        server_default="received",
    )

    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    received_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )

    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    conversation = relationship(
        "Conversation",
        back_populates="messages",
    )

    attachments = relationship(
        "MessageAttachment",
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="MessageAttachment.id",
    )

    sender_user = relationship("User")
