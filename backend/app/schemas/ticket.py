"""Support ticket and SLA API schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TicketCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    customer_id: int
    conversation_id: int | None = None
    status: str = Field(default="open", min_length=1, max_length=30)
    priority: str = Field(default="normal", min_length=1, max_length=20)
    assigned_user_id: int | None = None
    sla_due_at: datetime | None = None


class TicketUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    customer_id: int | None = None
    conversation_id: int | None = None
    status: str | None = Field(default=None, min_length=1, max_length=30)
    priority: str | None = Field(default=None, min_length=1, max_length=20)
    assigned_user_id: int | None = None
    sla_due_at: datetime | None = None


class TicketCommentCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=10000)


class TicketCommentOut(BaseModel):
    id: int
    ticket_id: int
    body: str
    author_user_id: int | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TicketOut(BaseModel):
    id: int
    business_id: int
    customer_id: int
    conversation_id: int | None = None
    title: str
    description: str | None = None
    status: str
    priority: str
    assigned_user_id: int | None = None
    sla_due_at: datetime | None = None
    resolved_at: datetime | None = None
    channel: str | None = None
    customer_name: str | None = None
    comments: list[TicketCommentOut] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TicketListOut(BaseModel):
    items: list[TicketOut]
    total: int


class TicketStatusItem(BaseModel):
    status: str
    ticket_count: int


class TicketReportOut(BaseModel):
    items: list[TicketStatusItem]
    total_tickets: int
    overdue_tickets: int


class TicketHistoryEventOut(BaseModel):
    id: int
    business_id: int
    ticket_id: int
    event_type: str
    from_value: str | None = None
    to_value: str | None = None
    actor_user_id: int | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TicketHistoryOut(BaseModel):
    items: list[TicketHistoryEventOut]
    total: int


class SlaNotificationOut(BaseModel):
    ticket_id: int
    business_id: int
    customer_id: int
    conversation_id: int | None = None
    title: str
    priority: str
    status: str
    assigned_user_id: int | None = None
    sla_due_at: datetime
    overdue_seconds: int


class SlaNotificationListOut(BaseModel):
    items: list[SlaNotificationOut]
    total: int
