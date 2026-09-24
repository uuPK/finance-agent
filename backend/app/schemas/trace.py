"""Versioned, public execution trace contract (never hidden model reasoning)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

TraceStatus = Literal["pending", "running", "passed", "failed", "skipped"]


class TraceStage(BaseModel):
    query_id: UUID
    stage: str = Field(min_length=1)
    clarification_round: int | None = Field(default=0, ge=0)
    stage_attempt: int | None = Field(default=0, ge=0)
    span_id: UUID | None = None
    parent_span_id: UUID | None = None


class TraceEvent(TraceStage):
    """An event to persist; query_id is also the trace identifier."""

    schema_version: int = Field(default=2, ge=1)
    type: str = Field(min_length=1)
    status: TraceStatus
    summary: str
    output: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_new_coordinates(self) -> TraceEvent:
        if self.schema_version >= 2 and (
            self.clarification_round is None or self.stage_attempt is None
        ):
            raise ValueError("Version 2 trace events require both stage coordinates")
        return self
