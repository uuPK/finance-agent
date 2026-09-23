from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, PrivateAttr

from app.schemas.query_plan import QueryFilter, QueryMetric, QueryPlan

__all__ = [
    "AgentStep",
    "GuardrailCheck",
    "QueryFilter",
    "QueryMetric",
    "QueryPlan",
    "QueryRequest",
    "QueryResponse",
]


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    user_id: str | None = None
    include_debug: bool = True


class GuardrailCheck(BaseModel):
    name: str
    passed: bool
    message: str
    severity: Literal["info", "warning", "error"] = "info"


class AgentStep(BaseModel):
    name: str
    status: Literal["pending", "running", "passed", "failed", "skipped"]
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class EvaluationExecutionArtifact(BaseModel):
    """Complete bounded SQL output retained only for internal evaluation."""

    status: Literal["success", "failed", "timeout"]
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False


class QueryResponse(BaseModel):
    _evaluation_execution_artifact: EvaluationExecutionArtifact | None = PrivateAttr(
        default=None
    )

    query_id: UUID = Field(default_factory=uuid4)
    status: Literal["planned", "completed", "failed", "needs_clarification"] = "planned"
    answer: str
    query_plan: QueryPlan | None = None
    sql: str | None = None
    result_preview: list[dict[str, Any]] = Field(default_factory=list)
    guardrail_checks: list[GuardrailCheck] = Field(default_factory=list)
    steps: list[AgentStep] = Field(default_factory=list)
    retry_count: int = 0
    elapsed_ms: int = 0
