from datetime import datetime

from pydantic import BaseModel, Field


class UnifiedMessage(BaseModel):
    channel: str
    external_user_id: str | None = None
    external_message_id: str | None = None
    content: str | None = None
    sent_at: datetime | None = None
    raw_payload: dict = Field(default_factory=dict)
