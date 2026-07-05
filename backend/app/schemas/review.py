from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.query_plan import ClarificationQuestion


ReviewStage = Literal["query_plan_review", "sql_review", "result_review"]


class ReviewDecision(BaseModel):
    passed: bool
    score: int = Field(ge=0, le=100)
    stage: ReviewStage
    error_type: str | None = None
    reason: str
    evidence: list[str] = Field(default_factory=list)
    repair_hint: str | None = None
    clarification_questions: list[ClarificationQuestion] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class ReviewBundle(BaseModel):
    hard_checks: list[ReviewDecision] = Field(default_factory=list)
    llm_checks: list[ReviewDecision] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in [*self.hard_checks, *self.llm_checks])
