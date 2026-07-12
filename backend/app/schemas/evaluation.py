# ruff: noqa: E501
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

Difficulty = Literal["simple", "medium", "complex"]
ReviewVerdict = Literal["correct", "incorrect", "needs_clarification", "insufficient_data"]
ReviewSeverity = Literal["minor", "major", "blocking"]


class EvaluationRunCreate(BaseModel):
    run_name: str = Field(default="manual-evaluation", min_length=1, max_length=128)
    difficulty: Difficulty | None = None
    limit: int = Field(default=20, ge=1, le=200)
    evaluation_mode: Literal["smoke", "full"] = "full"


class EvaluationRunCreated(BaseModel):
    eval_run_id: UUID
    status: str


class EvaluationRunSummary(BaseModel):
    eval_run_id: UUID
    run_name: str
    status: str
    total_cases: int
    passed_cases: int
    review_queued_cases: int = 0
    average_elapsed_ms: float | None = None
    dataset_version: str | None = None
    started_at: datetime
    finished_at: datetime | None = None


class EvaluationDashboard(BaseModel):
    total_cases: int
    active_cases: int
    executable_rate: float
    result_accuracy: float
    first_pass_rate: float
    repaired_pass_rate: float
    average_elapsed_ms: float | None = None
    pending_review_count: int
    reviewed_count: int
    latest_run: EvaluationRunSummary | None = None


class EvaluationResultSummary(BaseModel):
    eval_result_id: UUID
    case_id: UUID
    case_code: str
    question: str
    difficulty: Difficulty
    expected_status: str
    passed: bool
    executable: bool
    result_correct: bool | None = None
    plan_score: float | None = None
    sql_score: float | None = None
    result_score: float | None = None
    elapsed_ms: int | None = None
    failure_type: str | None = None
    failure_reason: str | None = None
    auto_decision: str
    review_priority: str | None = None
    review_status: str
    risk_reasons: list[str] = Field(default_factory=list)


class EvaluationRunDetail(EvaluationRunSummary):
    results: list[EvaluationResultSummary] = Field(default_factory=list)


class ReviewBatchCreate(BaseModel):
    batch_name: str = Field(default="human-review", min_length=1, max_length=128)
    max_items: int = Field(default=50, ge=1, le=500)
    created_by: str = Field(default="system", min_length=1, max_length=128)


class ReviewBatchSummary(BaseModel):
    review_batch_id: UUID
    batch_name: str
    status: str
    item_count: int
    dataset_version: str | None = None
    created_at: datetime


class ReviewDecisionInput(BaseModel):
    review_item_id: UUID
    reviewer_id: str = Field(min_length=1, max_length=128)
    verdict: ReviewVerdict
    error_class: str | None = Field(default=None, max_length=64)
    severity: ReviewSeverity = "minor"
    corrected_query_plan: dict[str, Any] = Field(default_factory=dict)
    corrected_sql: str | None = None
    corrected_result: dict[str, Any] = Field(default_factory=dict)
    reviewer_note: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    source_checksum: str | None = Field(default=None, max_length=128)


class ReviewImportRequest(BaseModel):
    decisions: list[ReviewDecisionInput] = Field(min_length=1, max_length=1000)


class ReviewImportResult(BaseModel):
    accepted: int
    rejected: list[str] = Field(default_factory=list)


class ReviewItemDetail(BaseModel):
    review_item_id: UUID
    review_batch_id: UUID
    status: str
    priority: str
    risk_reasons: list[str] = Field(default_factory=list)
    case_code: str
    question: str
    difficulty: Difficulty
    expected_status: str
    expected_query_plan: dict[str, Any] = Field(default_factory=dict)
    expected_sql: str | None = None
    expected_result: dict[str, Any] = Field(default_factory=dict)
    generated_query_plan: dict[str, Any] = Field(default_factory=dict)
    generated_sql: str | None = None
    generated_response: dict[str, Any] = Field(default_factory=dict)
    auto_decision: str
    failure_type: str | None = None
    failure_reason: str | None = None
    elapsed_ms: int | None = None
