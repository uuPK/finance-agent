"""Pure, conservative failure-domain routing. No tools or models are called here."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from app.schemas.v2_protocol import FailureEvent, HarnessAction

_SAFE_ERROR_TYPE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_MISSING_CONTEXT = {"missing_context", "missing_metadata_context"}


def safe_error_type(value: str | None, default: str) -> str:
    """Never put arbitrary critic text in a routing decision or Trace."""
    if value and _SAFE_ERROR_TYPE.fullmatch(value):
        return value
    return default


def classify_unknown_column(
    *, live_schema_has_column: bool | None, context_has_column: bool
) -> str:
    """Classify an unknown column only from a read-only live-schema comparison."""
    if live_schema_has_column is None:
        return "column_not_found"
    if live_schema_has_column and not context_has_column:
        return "missing_metadata_context"
    if not live_schema_has_column and context_has_column:
        return "stale_metadata_schema"
    if not live_schema_has_column:
        return "unknown_column_in_sql"
    return "column_not_found"


@dataclass(frozen=True, slots=True)
class RouteDecision:
    route_id: UUID
    route_attempt: int
    failure_stage: str
    error_type: str
    source_stage: str
    source_attempt: int
    candidate_action: HarnessAction
    final_action: HarnessAction
    reason_code: str


class FailureRouter:
    """Propose an action from explicit failure type; budget belongs to Harness."""

    @staticmethod
    def propose(failure: FailureEvent) -> HarnessAction:
        if not failure.retryable:
            return HarnessAction.TERMINATE
        if failure.stage in {"plan", "sql", "retrieval"} and failure.error_type in _MISSING_CONTEXT:
            return HarnessAction.CONTEXT_REFRESH
        if failure.stage == "plan":
            return HarnessAction.PLAN_REPAIR
        if failure.stage == "sql":
            return HarnessAction.SQL_REPAIR
        if failure.stage == "execution":
            if failure.error_type in {"sql_syntax_error", "unknown_column_in_sql"}:
                return HarnessAction.SQL_REPAIR
            if failure.error_type == "missing_metadata_context":
                return HarnessAction.CONTEXT_REFRESH
            # Unknown columns need live-schema/context provenance. A timeout is not
            # proof of a transient failure; neither should be blindly retried.
            return HarnessAction.TERMINATE
        if failure.stage == "result":
            return HarnessAction.SQL_REPAIR
        return HarnessAction.TERMINATE
