from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

EvidenceSourceType = Literal[
    "user_explicit",
    "metadata_definition",
    "system_default",
    "llm_inferred",
]
MissingContextType = Literal[
    "table", "column", "metric", "business_term", "join_path", "example"
]
FailureStage = Literal["plan", "sql", "execution", "result", "retrieval"]
FailurePriority = Literal["high", "medium", "low"]


class EvidenceRef(BaseModel):
    source_type: EvidenceSourceType
    source_id: str | None = None
    source_text: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class MissingContextRequest(BaseModel):
    type: MissingContextType
    concept: str = Field(min_length=1)
    from_table: str | None = None
    to_table: str | None = None
    reason: str = Field(min_length=1)
    priority: FailurePriority = "medium"


class FailureEvent(BaseModel):
    stage: FailureStage
    error_type: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    repair_hint: str | None = None
    retryable: bool = False


class HarnessAction(StrEnum):
    CONTINUE = "CONTINUE"
    PLAN_REPAIR = "PLAN_REPAIR"
    SQL_REPAIR = "SQL_REPAIR"
    CONTEXT_REFRESH = "CONTEXT_REFRESH"
    RETRY_EXECUTION = "RETRY_EXECUTION"
    CLARIFY = "CLARIFY"
    TERMINATE = "TERMINATE"
