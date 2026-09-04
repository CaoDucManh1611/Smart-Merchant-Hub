"""Workflow automation API contracts."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


WORKFLOW_EVENTS = (
    "message.created",
    "ticket.created",
    "ticket.status_changed",
    "lead.stage_changed",
    "order.created",
)
WORKFLOW_ACTIONS = ("create_ticket", "assign_user", "add_tag")


class WorkflowAction(BaseModel):
    type: Literal["create_ticket", "assign_user", "add_tag"]
    title: str | None = Field(default=None, max_length=255)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    user_id: int | None = None
    tag: str | None = Field(default=None, max_length=80)


class WorkflowCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    event_type: str = Field(..., min_length=1, max_length=60)
    conditions: dict[str, Any] = Field(default_factory=dict)
    actions: list[WorkflowAction] = Field(..., min_length=1, max_length=10)
    enabled: bool = True

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        if value not in WORKFLOW_EVENTS:
            raise ValueError(f"event_type không hợp lệ. Chọn: {', '.join(WORKFLOW_EVENTS)}")
        return value


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    event_type: str | None = Field(default=None, min_length=1, max_length=60)
    conditions: dict[str, Any] | None = None
    actions: list[WorkflowAction] | None = Field(default=None, min_length=1, max_length=10)
    enabled: bool | None = None

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str | None) -> str | None:
        if value is not None and value not in WORKFLOW_EVENTS:
            raise ValueError(f"event_type không hợp lệ. Chọn: {', '.join(WORKFLOW_EVENTS)}")
        return value


class WorkflowOut(BaseModel):
    id: int
    business_id: int
    name: str
    event_type: str
    conditions: dict[str, Any]
    actions: list[dict[str, Any]]
    enabled: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class WorkflowListOut(BaseModel):
    items: list[WorkflowOut]
    total: int


class WorkflowRunRequest(BaseModel):
    event_id: str = Field(..., min_length=1, max_length=255)
    event_type: str = Field(..., min_length=1, max_length=60)
    payload: dict[str, Any] = Field(default_factory=dict)
    delay_seconds: int = Field(default=0, ge=0, le=604800)


class WorkflowRunOut(BaseModel):
    id: int | None = None
    workflow_id: int
    event_id: str
    status: str
    matched: bool
    error_message: str | None = None
    executed_at: datetime | None = None
    attempts: int = 1
    next_run_at: datetime | None = None
