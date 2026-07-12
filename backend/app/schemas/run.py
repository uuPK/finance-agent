from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.query import QueryResponse

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
StepStatus = Literal["pending", "running", "passed", "failed", "skipped"]


class QueryRunCreate(BaseModel):
    question: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1, max_length=128)


class QueryRunCreated(BaseModel):
    query_id: UUID
    status: RunStatus
    stream_url: str


class QueryEvent(BaseModel):
    event_id: int
    query_id: UUID
    type: str
    stage: str
    status: StepStatus
    attempt: int = 0
    summary: str
    output: dict[str, Any] = Field(default_factory=dict)
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
    response: QueryResponse | None = None
    events: list[QueryEvent] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class QueryRunList(BaseModel):
    items: list[QueryRunSnapshot]
    total: int
    limit: int
    offset: int
