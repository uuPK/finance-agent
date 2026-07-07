from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.schemas.query_plan import QueryPlan
from app.schemas.review import ReviewDecision
from app.services.sql_executor import SQLExecutionResult


ResultSeverity = Literal["info", "warning", "error"]


@dataclass(frozen=True, slots=True)
class ResultFinding:
    name: str
    passed: bool
    message: str
    severity: ResultSeverity = "info"


@dataclass(slots=True)
class ResultValidationResult:
    passed: bool
    checks: list[ReviewDecision] = field(default_factory=list)
    score: int = 100
    error_type: str | None = None
    repair_hint: str | None = None


class ResultHardValidator:
    """Validate SQL execution output before returning it to the user."""

    def __init__(
        self,
        max_result_rows: int = 1000,
        sensitive_columns: set[str] | None = None,
    ) -> None:
        self.max_result_rows = max_result_rows
        self.sensitive_columns = {
            "phone",
            "mobile",
            "mobile_phone",
            "id_no",
            "id_number",
            "cert_no",
            "bank_account",
            "address",
            *(sensitive_columns or set()),
        }

    def validate(
        self,
        query_plan: QueryPlan,
        execution_result: SQLExecutionResult,
    ) -> ResultValidationResult:
        findings = [
            self._check_execution_success(execution_result),
            self._check_row_limit(execution_result),
            self._check_columns_present(execution_result),
            self._check_sensitive_columns(execution_result),
            self._check_grain(query_plan, execution_result),
            self._check_empty_result(execution_result),
        ]
        checks = [self._to_review_decision(finding) for finding in findings]
        failed_errors = [
            check for check in checks if not check.passed and check.error_type
        ]
        passed = not failed_errors
        score = self._score(checks)
        primary_failure = failed_errors[0] if failed_errors else None
        return ResultValidationResult(
            passed=passed,
            checks=checks,
            score=score,
            error_type=primary_failure.error_type if primary_failure else None,
            repair_hint=primary_failure.repair_hint if primary_failure else None,
        )

    def _check_execution_success(
        self, execution_result: SQLExecutionResult
    ) -> ResultFinding:
        if execution_result.status == "success":
            return ResultFinding(
                name="execution_success",
                passed=True,
                message="SQL executed successfully.",
            )
        return ResultFinding(
            name=execution_result.error_type or "sql_execution_error",
            passed=False,
            message=execution_result.error_message or "SQL execution failed.",
            severity="error",
        )

    def _check_row_limit(self, execution_result: SQLExecutionResult) -> ResultFinding:
        if execution_result.status != "success":
            return ResultFinding(
                name="row_limit",
                passed=True,
                message="Row-limit check skipped because SQL did not execute.",
                severity="warning",
            )
        if execution_result.truncated:
            return ResultFinding(
                name="result_too_large",
                passed=False,
                message=(
                    f"Result exceeds max_result_rows={self.max_result_rows}; "
                    "query must aggregate, filter, or lower LIMIT."
                ),
                severity="error",
            )
        return ResultFinding(
            name="row_limit",
            passed=True,
            message=f"Returned {execution_result.row_count} rows within limit.",
        )

    def _check_columns_present(self, execution_result: SQLExecutionResult) -> ResultFinding:
        if execution_result.status != "success":
            return ResultFinding(
                name="result_columns",
                passed=True,
                message="Column check skipped because SQL did not execute.",
                severity="warning",
            )
        if not execution_result.columns:
            return ResultFinding(
                name="empty_columns",
                passed=False,
                message="SQL returned no columns.",
                severity="error",
            )
        return ResultFinding(
            name="result_columns",
            passed=True,
            message="SQL returned a non-empty column schema.",
        )

    def _check_sensitive_columns(
        self, execution_result: SQLExecutionResult
    ) -> ResultFinding:
        returned = {column.lower() for column in execution_result.columns}
        sensitive = returned & self.sensitive_columns
        if sensitive:
            return ResultFinding(
                name="sensitive_result_column",
                passed=False,
                message=f"Result contains sensitive columns: {', '.join(sorted(sensitive))}.",
                severity="error",
            )
        return ResultFinding(
            name="sensitive_result_column",
            passed=True,
            message="Result does not expose sensitive columns.",
        )

    def _check_grain(
        self, query_plan: QueryPlan, execution_result: SQLExecutionResult
    ) -> ResultFinding:
        if execution_result.status != "success":
            return ResultFinding(
                name="result_grain",
                passed=True,
                message="Grain check skipped because SQL did not execute.",
                severity="warning",
            )

        grain_level = query_plan.grain.level if query_plan.grain else "unknown"
        columns = {column.lower() for column in execution_result.columns}
        if grain_level == "customer":
            if columns & {"customer_id", "customer_no", "客户编号", "客户id"}:
                return ResultFinding(
                    name="result_grain",
                    passed=True,
                    message="Customer-grain result includes a customer identifier.",
                )
            return ResultFinding(
                name="wrong_grain",
                passed=False,
                message="Customer-grain query result lacks customer_id or customer_no.",
                severity="error",
            )
        if grain_level == "manager":
            if columns & {"manager_id", "manager_no", "manager_name_masked", "org_code"}:
                return ResultFinding(
                    name="result_grain",
                    passed=True,
                    message="Manager-grain result includes a manager or org identifier.",
                )
            return ResultFinding(
                name="wrong_grain",
                passed=False,
                message="Manager-grain query result lacks manager or org identifier.",
                severity="error",
            )

        return ResultFinding(
            name="result_grain",
            passed=True,
            message=f"No strict grain requirement for grain={grain_level}.",
        )

    def _check_empty_result(self, execution_result: SQLExecutionResult) -> ResultFinding:
        if execution_result.status != "success":
            return ResultFinding(
                name="empty_result",
                passed=True,
                message="Empty-result check skipped because SQL did not execute.",
                severity="warning",
            )
        if execution_result.row_count == 0:
            return ResultFinding(
                name="empty_result",
                passed=True,
                message=(
                    "SQL returned zero rows. This may be valid for restrictive filters; "
                    "semantic result review can decide whether repair is needed."
                ),
                severity="warning",
            )
        return ResultFinding(
            name="empty_result",
            passed=True,
            message="SQL returned at least one row.",
        )

    def _to_review_decision(self, finding: ResultFinding) -> ReviewDecision:
        return ReviewDecision(
            passed=finding.passed,
            score=100 if finding.passed else 0,
            stage="result_review",
            error_type=None if finding.passed else finding.name,
            reason=finding.message,
            evidence=[finding.name],
            repair_hint=None if finding.passed else self._repair_hint(finding.name),
            confidence=1.0,
        )

    def _repair_hint(self, error_type: str) -> str:
        hints = {
            "column_not_found": "Regenerate SQL using only columns from schema context.",
            "table_not_found": "Regenerate SQL using only tables from schema context.",
            "sql_syntax_error": "Regenerate syntactically valid PostgreSQL SQL.",
            "timeout": "Add stronger filters, aggregate earlier, or reduce LIMIT.",
            "result_too_large": "Lower LIMIT or aggregate/filter the query result.",
            "empty_columns": "Select explicit output columns or aggregate expressions.",
            "sensitive_result_column": "Remove sensitive fields from SELECT output.",
            "wrong_grain": "Adjust SELECT and GROUP BY to match QueryPlan grain.",
        }
        return hints.get(error_type, "Regenerate SQL to satisfy result hard validation.")

    def _score(self, checks: list[ReviewDecision]) -> int:
        if not checks:
            return 0
        return int(sum(check.score for check in checks) / len(checks))
