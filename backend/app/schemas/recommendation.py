"""Public contracts for tenant-scoped recommendation serving and feedback."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RagCandidate(BaseModel):
    product_id: int = Field(..., ge=1)
    relevance: float = Field(..., ge=0, le=1)


class RecommendationRequestCreate(BaseModel):
    customer_id: int | None = Field(default=None, ge=1)
    limit: int = Field(default=5, ge=1, le=20)
    query: str | None = Field(default=None, max_length=1000)
    context: dict[str, Any] = Field(default_factory=dict)
    rag_candidates: list[RagCandidate] = Field(default_factory=list, max_length=100)
    experiment_id: int | None = Field(default=None, ge=1)


class RecommendationItemOut(BaseModel):
    product_id: int
    sku: str
    name: str
    price: float
    score: float
    reason: str


class RecommendationResponse(BaseModel):
    request_id: str
    customer_id: int | None = None
    segment: str | None = None
    strategy: str
    model_version: str
    candidate_count: int
    items: list[RecommendationItemOut]
    created_at: datetime | None = None


class RecommendationFeedbackCreate(BaseModel):
    product_id: int = Field(..., ge=1)
    event_type: Literal["impression", "click", "cart", "purchase", "skip", "refund"]
    idempotency_key: str = Field(..., min_length=1, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecommendationFeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    request_id: str
    product_id: int
    event_type: str
    reward: float
    occurred_at: datetime | None = None


InteractionEventType = Literal[
    "view", "search", "ask", "impression", "click", "cart", "purchase", "skip", "refund"
]
InteractionSource = Literal["web", "chatbot", "rag", "recommendation", "order", "api"]


class RecommendationInteractionCreate(BaseModel):
    customer_id: int | None = Field(default=None, ge=1)
    product_id: int | None = Field(default=None, ge=1)
    request_id: str | None = Field(default=None, min_length=1, max_length=64)
    event_type: InteractionEventType
    source: InteractionSource = "api"
    query: str | None = Field(default=None, max_length=1000)
    idempotency_key: str = Field(..., min_length=1, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None


class RecommendationInteractionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_id: int | None = None
    product_id: int | None = None
    request_id: str | None = None
    event_type: str
    source: str
    occurred_at: datetime | None = None


class RecommendationInteractionSummaryOut(BaseModel):
    customer_id: int | None = None
    days: int
    total_events: int
    event_counts: dict[str, int]
    top_product_ids: list[int]


class RecommendationTrainingScheduleOut(BaseModel):
    training_run_id: int
    job_id: int
    status: str
