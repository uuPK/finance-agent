from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from time import perf_counter
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.config import get_settings
from app.db.session import engine as default_engine


SQLExecutionStatus = Literal["success", "failed", "timeout"]


@dataclass(slots=True)
class SQLExecutionResult:
    status: SQLExecutionStatus
    sql: str
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    elapsed_ms: int = 0
    error_type: str | None = None
    error_message: str | None = None


class SQLExecutor:
    """Execute reviewed SELECT SQL in a read-only PostgreSQL transaction."""

    def __init__(
        self,
        engine: Engine | None = None,
        timeout_seconds: int | None = None,
        max_result_rows: int | None = None,
    ) -> None:
        settings = get_settings()
        self.engine = engine or default_engine
        self.timeout_seconds = timeout_seconds or settings.sql_timeout_seconds
        self.max_result_rows = max_result_rows or settings.max_result_rows

    def execute(self, sql: str) -> SQLExecutionResult:
        started_at = perf_counter()
        try:
            with self.engine.connect() as connection:
                transaction = connection.begin()
                try:
                    connection.execute(text("SET TRANSACTION READ ONLY"))
                    connection.execute(
                        text("select set_config('statement_timeout', :timeout, true)"),
                        {"timeout": f"{self.timeout_seconds * 1000}ms"},
                    )
                    result = connection.execute(text(sql))
                    result_columns = list(result.keys())
                    fetched_rows = result.mappings().fetchmany(self.max_result_rows + 1)
                    transaction.rollback()
                except Exception:
                    transaction.rollback()
                    raise

            truncated = len(fetched_rows) > self.max_result_rows
            visible_rows = fetched_rows[: self.max_result_rows]
            rows = [
                {key: self._jsonable(value) for key, value in row.items()}
                for row in visible_rows
            ]
            columns = list(rows[0].keys()) if rows else result_columns
            return SQLExecutionResult(
                status="success",
                sql=sql,
                columns=columns,
                rows=rows,
                row_count=len(rows),
                truncated=truncated,
                elapsed_ms=int((perf_counter() - started_at) * 1000),
            )
        except Exception as exc:
            error_message = str(exc)
            return SQLExecutionResult(
                status="timeout" if self._is_timeout(error_message) else "failed",
                sql=sql,
                elapsed_ms=int((perf_counter() - started_at) * 1000),
                error_type=self._classify_error(error_message),
                error_message=error_message,
            )

    def _classify_error(self, error_message: str) -> str:
        lowered = error_message.lower()
        if self._is_timeout(error_message):
            return "timeout"
        if "does not exist" in lowered and "column" in lowered:
            return "column_not_found"
        if "does not exist" in lowered and ("relation" in lowered or "table" in lowered):
            return "table_not_found"
        if "syntax error" in lowered:
            return "sql_syntax_error"
        if "read-only" in lowered or "read only" in lowered:
            return "readonly_violation"
        return "sql_execution_error"

    def _is_timeout(self, error_message: str) -> bool:
        lowered = error_message.lower()
        return "statement timeout" in lowered or "query canceled" in lowered

    def _jsonable(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date | time):
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
        return value
