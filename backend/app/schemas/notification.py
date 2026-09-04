from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotificationOut(BaseModel):
    id: int
    business_id: int
    user_id: int | None = None
    kind: str
    title: str
    body: str | None = None
    metadata: dict = Field(default_factory=dict, validation_alias="metadata_")
    is_read: bool
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
