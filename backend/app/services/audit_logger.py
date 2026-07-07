from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.session import engine as default_engine
from app.guardrails.result_validator import ResultValidationResult
from app.schemas.review import ReviewDecision
from app.services.sql_executor import SQLExecutionResult


class QueryAuditLogger:
    """Best-effort persistence for query, SQL execution, and result validation logs."""

    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or default_engine

    def start_query_run(
        self,
        query_id: UUID,
        question: str,
        user_id: str | None,
    ) -> None:
        self._safe_execute(
            """
            insert into agent.query_runs (query_id, user_id, question, status)
            values (:query_id, :user_id, :question, 'received')
            on conflict (query_id) do update set
                user_id = excluded.user_id,
                question = excluded.question,
                status = excluded.status,
                updated_at = now()
            """,
            {
                "query_id": str(query_id),
                "user_id": user_id,
                "question": question,
            },
        )

    def finish_query_run(
        self,
        query_id: UUID,
        status: str,
        final_answer: str,
        final_sql: str | None,
        retry_count: int,
        elapsed_ms: int,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self._safe_execute(
            """
            update agent.query_runs
            set
                status = :status,
                final_answer = :final_answer,
                final_sql = :final_sql,
                retry_count = :retry_count,
                elapsed_ms = :elapsed_ms,
                error_type = :error_type,
                error_message = :error_message,
                updated_at = now()
            where query_id = :query_id
            """,
            {
                "query_id": str(query_id),
                "status": status,
                "final_answer": final_answer,
                "final_sql": final_sql,
                "retry_count": retry_count,
                "elapsed_ms": elapsed_ms,
                "error_type": error_type,
                "error_message": error_message,
            },
        )

    def log_sql_execution(
        self,
        query_id: UUID,
        attempt: int,
        result: SQLExecutionResult,
    ) -> str | None:
        try:
            with self.engine.begin() as connection:
                execution_id = connection.execute(
                    text(
                        """
                        insert into agent.sql_execution_logs
                            (
                                query_id,
                                attempt,
                                sql_text,
                                execution_status,
                                row_count,
                                result_schema,
                                result_preview,
                                elapsed_ms,
                                error_message
                            )
                        values
                            (
                                :query_id,
                                :attempt,
                                :sql_text,
                                :execution_status,
                                :row_count,
                                cast(:result_schema as jsonb),
                                cast(:result_preview as jsonb),
                                :elapsed_ms,
                                :error_message
                            )
                        returning execution_id
                        """
                    ),
                    {
                        "query_id": str(query_id),
                        "attempt": attempt,
                        "sql_text": result.sql,
                        "execution_status": result.status,
                        "row_count": result.row_count,
                        "result_schema": json.dumps(
                            [{"name": column} for column in result.columns],
                            ensure_ascii=False,
                        ),
                        "result_preview": json.dumps(result.rows[:20], ensure_ascii=False),
                        "elapsed_ms": result.elapsed_ms,
                        "error_message": result.error_message,
                    },
                ).scalar_one()
                return str(execution_id)
        except Exception:
            return None

    def log_result_validation(
        self,
        query_id: UUID,
        execution_id: str | None,
        result: ResultValidationResult,
        critic_review: dict[str, Any] | None = None,
        hard_checks: list[ReviewDecision] | None = None,
    ) -> None:
        checks_to_log = hard_checks or result.checks
        self._safe_execute(
            """
            insert into agent.result_validation_logs
                (
                    query_id,
                    execution_id,
                    hard_checks,
                    critic_review,
                    passed,
                    score,
                    error_type,
                    repair_hint
                )
            values
                (
                    :query_id,
                    cast(:execution_id as uuid),
                    cast(:hard_checks as jsonb),
                    cast(:critic_review as jsonb),
                    :passed,
                    :score,
                    :error_type,
                    :repair_hint
                )
            """,
            {
                "query_id": str(query_id),
                "execution_id": execution_id,
                "hard_checks": json.dumps(
                    [check.model_dump(mode="json") for check in checks_to_log],
                    ensure_ascii=False,
                ),
                "critic_review": json.dumps(critic_review or {}, ensure_ascii=False),
                "passed": result.passed,
                "score": result.score,
                "error_type": result.error_type,
                "repair_hint": result.repair_hint,
            },
        )

    def _safe_execute(self, sql: str, params: dict[str, Any]) -> None:
        try:
            with self.engine.begin() as connection:
                connection.execute(text(sql), params)
        except Exception:
            return
