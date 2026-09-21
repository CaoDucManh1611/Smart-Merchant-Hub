"""API contracts for chatbot runtime controls."""

from datetime import date, datetime
from typing import Any, Literal

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
        special_dates = value.get("special_dates", {})
        if not isinstance(special_dates, dict) or len(special_dates) > 366:
            raise ValueError("Ngày giờ đặc biệt phải là một danh sách tối đa 366 ngày")
        for special_day, rule in special_dates.items():
            try:
                date.fromisoformat(str(special_day))
            except ValueError as exc:
                raise ValueError("Ngày đặc biệt phải có dạng YYYY-MM-DD") from exc
            if not isinstance(rule, dict) or not isinstance(rule.get("closed", False), bool):
                raise ValueError("Thiết lập ngày đặc biệt không hợp lệ")
            windows = rule.get("windows", [])
            if not isinstance(windows, list) or len(windows) > 4:
                raise ValueError("Ngày đặc biệt tối đa 4 khung giờ")
            for window in windows:
                if not isinstance(window, (list, tuple)) or len(window) != 2:
                    raise ValueError("Khung giờ phải có giờ bắt đầu và kết thúc")
                for item in window:
                    if not isinstance(item, str) or len(item) != 5 or item[2] != ":":
                        raise ValueError("Giờ phải có dạng HH:MM")
        for day, windows in value.items():
            if day in {"timezone", "special_dates"}:
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
    # Optional inbound/run correlation for the unified audit stream. Keep it
    # separate from tool arguments so models cannot smuggle arbitrary audit
    # metadata through a tool implementation.
    correlation_id: str | None = Field(default=None, min_length=1, max_length=120)


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


class ChatbotResponseFeedbackRequest(BaseModel):
    """A lightweight, explicit signal used to improve bot responses.

    The signal is intentionally binary.  It is enough to safely measure a
    response policy without pretending that one click is a training label for
    an entire language model.
    """

    rating: Literal[-1, 1]
    comment: str | None = Field(default=None, max_length=1000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class ChatbotResponseFeedbackOut(BaseModel):
    message_id: int
    rating: Literal[-1, 1]
    recorded: bool = True


class LearningTopicOut(BaseModel):
    key: str
    label: str
    message_count: int
    conversation_count: int
    examples: list[str] = Field(default_factory=list)


class LearningSummaryOut(BaseModel):
    period_days: int
    inbound_messages: int
    conversations_sampled: int
    topics: list[LearningTopicOut] = Field(default_factory=list)
    response_feedback: dict[str, int | float] = Field(default_factory=dict)
    method: str


class TopicSuggestionOut(BaseModel):
    suggestion_id: str
    label: str
    message_count: int
    conversation_count: int
    examples: list[str] = Field(default_factory=list)
    top_terms: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    review_status: Literal["pending_review"] = "pending_review"
    source: Literal["stored_embeddings", "deterministic_local_embedding"]


class TopicDiscoveryOut(BaseModel):
    period_days: int
    messages_analyzed: int
    conversations_sampled: int
    suggestions: list[TopicSuggestionOut] = Field(default_factory=list)
    method: str
    knowledge_base_updated: Literal[False] = False
