"""API contracts for chatbot runtime controls."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatbotConfigUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    handoff_enabled: bool | None = None
    system_prompt: str | None = Field(default=None, max_length=8000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    similarity_threshold: float | None = Field(default=None, ge=0, le=1)
    allowed_channels: list[str] | None = None
    business_hours: dict[str, Any] | None = None

    @field_validator("business_hours")
    @classmethod
    def validate_business_hours(cls, value):
        if value is None:
            return value
        if "timezone" in value and not isinstance(value["timezone"], str):
            raise ValueError("timezone phải là chuỗi")
        for day, windows in value.items():
            if day == "timezone":
                continue
            if day not in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}:
                raise ValueError(f"Ngày không hợp lệ: {day}")
            if not isinstance(windows, list) or len(windows) > 4:
                raise ValueError("Mỗi ngày tối đa 4 khung giờ")
            for window in windows:
                if not isinstance(window, (list, tuple)) or len(window) != 2:
                    raise ValueError("Khung giờ phải có giờ bắt đầu và kết thúc")
                for item in window:
                    if not isinstance(item, str) or len(item) != 5 or item[2] != ":":
                        raise ValueError("Giờ phải có dạng HH:MM")
        return value


class ChatbotConfigOut(BaseModel):
    id: int
    business_id: int
    name: str
    enabled: bool
    handoff_enabled: bool
    system_prompt: str | None = None
    top_k: int
    similarity_threshold: float
    allowed_channels: list[str] | None = None
    business_hours: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)


class CannedResponseCreate(BaseModel):
    shortcut: str = Field(..., min_length=1, max_length=40, pattern=r"^/[a-zA-Z0-9_-]+$")
    title: str = Field(..., min_length=1, max_length=160)
    content: str = Field(..., min_length=1, max_length=10000)
    enabled: bool = True


class CannedResponseUpdate(BaseModel):
    shortcut: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^/[a-zA-Z0-9_-]+$")
    title: str | None = Field(default=None, min_length=1, max_length=160)
    content: str | None = Field(default=None, min_length=1, max_length=10000)
    enabled: bool | None = None


class CannedResponseOut(BaseModel):
    id: int
    business_id: int
    shortcut: str
    title: str
    content: str
    enabled: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CannedResponseListOut(BaseModel):
    items: list[CannedResponseOut]
    total: int


class BotModeRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class BotModeOut(BaseModel):
    conversation_id: int
    bot_mode: str
    reason: str | None = None


class ChatbotToolRequest(BaseModel):
    tool: str = Field(..., min_length=1, max_length=60)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ChatbotToolResponse(BaseModel):
    tool: str
    result: dict[str, Any]


class FollowUpCreate(BaseModel):
    conversation_id: int
    message: str = Field(..., min_length=1, max_length=10000)
    run_at: datetime
    kind: str = Field(default="custom", min_length=1, max_length=40)
    metadata: dict[str, Any] | None = None


class FollowUpOut(BaseModel):
    id: int
    business_id: int
    conversation_id: int
    customer_id: int
    kind: str
    message: str
    run_at: datetime
    status: str
    attempts: int
    created_at: datetime | None = None
    sent_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class FollowUpListOut(BaseModel):
    items: list[FollowUpOut]
    total: int


class CsatSummaryOut(BaseModel):
    responses: int
    average_rating: float
    satisfaction_rate: float
    bot_resolution_rate: float


class CustomerFeedbackOut(BaseModel):
    id: int
    business_id: int
    conversation_id: int
    customer_id: int
    ticket_id: int | None = None
    followup_id: int | None = None
    status: str
    rating: int | None = None
    comment: str | None = None
    requested_at: datetime | None = None
    responded_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class CustomerFeedbackListOut(BaseModel):
    items: list[CustomerFeedbackOut]
    total: int
    summary: CsatSummaryOut
