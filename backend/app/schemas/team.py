"""Tenant team directory and role schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


TEAM_ROLES = ("owner", "admin", "agent", "viewer", "business_agent")
TeamRole = Literal["owner", "admin", "agent", "viewer", "business_agent"]


class TeamUserCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=3, max_length=255)
    role: TeamRole = "agent"
    password: str | None = Field(default=None, min_length=8, max_length=256)


class TeamUserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    role: TeamRole | None = None
    is_active: bool | None = None


class TeamUserOut(BaseModel):
    id: int
    business_id: int
    full_name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TeamUserListOut(BaseModel):
    items: list[TeamUserOut]
    total: int
