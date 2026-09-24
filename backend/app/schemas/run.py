from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.query import QueryResponse
from app.schemas.trace import TraceEvent, TraceStatus

RunStatus = Literal[
    "received",
    "planned",
    "queued",
    "running",
    "completed",
    "failed",
    "needs_clarification",
    "interrupted",
]
StepStatus = TraceStatus


class QueryRunCreate(BaseModel):
    question: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1, max_length=128)


class QueryRunCreated(BaseModel):
    query_id: UUID
    status: RunStatus
    stream_url: str


class QueryEvent(TraceEvent):
    event_id: int
    # Missing trace fields in pre-5.0 API payloads represent a legacy event.
    schema_version: int = Field(default=1, ge=1)
    clarification_round: int | None = Field(default=None, ge=0)
    stage_attempt: int | None = Field(default=None, ge=0)
    # Deprecated display field. It is not a stable stage identity.
    attempt: int = 0
    occurred_at: datetime


class ClarificationAnswer(BaseModel):
    field: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)


class ClarificationSubmission(BaseModel):
    answers: list[ClarificationAnswer] = Field(..., min_length=1)


class QueryRunSnapshot(BaseModel):
    query_id: UUID
    user_id: str | None = None
    question: str
    status: RunStatus
    current_stage: str | None = None
    retry_count: int = 0
    elapsed_ms: int | None = None
    error_type: str | None = None
    error_message: str | None = None
    clarification_context: dict[str, Any] = Field(default_factory=dict)
    review_status: str = "not_requested"
    review_reason: str | None = None
    review_requested_at: datetime | None = None
    response: QueryResponse | None = None
    events: list[QueryEvent] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class QueryRunList(BaseModel):
    items: list[QueryRunSnapshot]
    total: int
    limit: int
    offset: int
