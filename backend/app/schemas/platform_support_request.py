"""Authoritative HTTP contract; FastAPI derives OpenAPI from these schemas."""
from datetime import datetime
from html import unescape
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SupportProvider = Literal['facebook', 'instagram', 'telegram', 'zalo', 'tiktok', 'shopee']
SupportStatus = Literal['open', 'in_progress', 'resolved', 'closed']


def clean_support_text(value: str) -> str:
    value = unescape(value)
    normalized = re.sub(r'<[^>]*>', '', value)
    normalized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', normalized).strip()
    # Only human summaries are accepted, never copied provider payloads or credentials.
    # shortcut: credential patterns cannot identify every secret; use structured fields if attachments are introduced.
    prohibited = r'(?i)(https?://|bearer\s|authorization\s*:|(?:access[_ -]?token|refresh[_ -]?token|token|password|secret|api[_ -]?key|client[_ -]?secret)\s*[:=]|traceback|[{}]|<\s*(?:script|style)\b|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|\b[A-Za-z0-9_-]{80,}\b)'
    if re.search(prohibited, value) or re.search(prohibited, normalized):
        raise ValueError('Describe the issue without links, credentials or raw provider diagnostics.')
    if not normalized:
        raise ValueError('A human-readable description is required.')
    return normalized


class SupportRequestCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: SupportProvider | None = None
    providers: list[SupportProvider] | None = Field(default=None, min_length=1, max_length=6)
    description: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=180, pattern=r'^[A-Za-z0-9_-]+$')

    _clean_description = field_validator('description')(clean_support_text)

    @model_validator(mode='after')
    def selected_channels(self):
        if self.providers is None:
            if self.provider is None:
                raise ValueError('Select at least one channel.')
            self.providers = [self.provider]
        if len(set(self.providers)) != len(self.providers):
            raise ValueError('Channels must be unique.')
        self.providers = sorted(self.providers)
        if self.provider is not None and self.provider not in self.providers:
            raise ValueError('Conflicting channel fields.')
        self.provider = self.providers[0]
        return self


class SupportRequestUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: SupportStatus | None = None
    response: str | None = Field(default=None, min_length=1, max_length=2000)
    assigned_admin_id: int | None = Field(default=None, gt=0)

    @field_validator('response')
    @classmethod
    def clean_response(cls, value):
        return clean_support_text(value) if value is not None else value

    @model_validator(mode='after')
    def meaningful_update(self):
        if not self.model_fields_set:
            raise ValueError('At least one update field is required.')
        for field in ('status', 'response'):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f'{field} cannot be null.')
        return self


class SupportHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_user_id: int
    from_status: SupportStatus | None
    to_status: SupportStatus
    response: str | None
    assigned_admin_id: int | None
    created_at: datetime


class SupportRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    business_id: int
    provider: SupportProvider
    providers: list[SupportProvider] | None = None
    description: str
    status: SupportStatus
    response: str | None
    assigned_admin_id: int | None
    created_at: datetime
    updated_at: datetime
    history: list[SupportHistoryOut]

    @model_validator(mode='after')
    def legacy_channels(self):
        self.providers = self.providers or [self.provider]
        return self


class SupportRequestListOut(BaseModel):
    channel_limit: int | None = None
    items: list[SupportRequestOut]
    total: int
    limit: int
    offset: int
