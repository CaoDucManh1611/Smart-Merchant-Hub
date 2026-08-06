from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(30), index=True)
    external_user_id: Mapped[str | None] = mapped_column(String(255))
    external_message_id: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict] = mapped_column(JSON)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
