from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.session import engine as default_engine
from app.schemas.query import QueryResponse
from app.schemas.run import QueryEvent, QueryRunSnapshot

_BLOCKED_KEYS = {
    "api_key",
    "authorization",
    "database_url",
    "system_prompt",
    "user_prompt",
    "llm_raw_response",
    "raw_response",
    "connection_string",
}
_SENSITIVE_COLUMNS = {
    "phone",
    "mobile",
    "mobile_phone",
    "id_no",
    "id_number",
    "cert_no",
    "bank_account",
    "address",
}
_SECRET_PATTERN = re.compile(r"(?i)(sk-[a-z0-9_-]{12,}|bearer\s+[a-z0-9._-]+)")
_DATABASE_PATTERN = re.compile(r"(?i)postgres(?:ql)?(?:\+\w+)?://[^\s]+")


def sanitize_event_payload(value: Any, key: str | None = None) -> Any:
    normalized_key = (key or "").lower()
    if normalized_key in _BLOCKED_KEYS or normalized_key in _SENSITIVE_COLUMNS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): sanitize_event_payload(item, str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_event_payload(item, key) for item in value]
    if isinstance(value, tuple):
        return [sanitize_event_payload(item, key) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        redacted = _SECRET_PATTERN.sub("[REDACTED]", value)
        return _DATABASE_PATTERN.sub("[REDACTED_DATABASE_URL]", redacted)
    if value is None or isinstance(value, bool | int | float):
        return value
    if hasattr(value, "model_dump"):
        return sanitize_event_payload(value.model_dump(mode="json"), key)
    return str(value)


class RunRepository:
    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or default_engine

    def create_run(self, query_id: UUID, question: str, user_id: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    insert into agent.query_runs
                        (query_id, user_id, question, status, current_stage)
                    values (:query_id, :user_id, :question, 'queued', 'receive_question')
                    """
                ),
                {"query_id": str(query_id), "user_id": user_id, "question": question},
            )

    def append_event(
        self,
        query_id: UUID,
        event_type: str,
        stage: str,
        status: str,
        summary: str,
        output: dict[str, Any] | None = None,
        attempt: int = 0,
    ) -> QueryEvent:
        payload = sanitize_event_payload(output or {})
        run_status = self._run_status(event_type, status)
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        """
                    insert into agent.query_events
                        (query_id, event_type, stage_name, step_status, attempt, summary, payload)
                    values
                        (:query_id, :event_type, :stage, :status, :attempt, :summary,
                         cast(:payload as jsonb))
                    returning event_id, created_at
                    """
                    ),
                    {
                        "query_id": str(query_id),
                        "event_type": event_type,
                        "stage": stage,
                        "status": status,
                        "attempt": attempt,
                        "summary": summary,
                        "payload": json.dumps(payload, ensure_ascii=False),
                    },
                )
                .mappings()
                .one()
            )
            connection.execute(
                text(
                    """
                    insert into agent.query_steps
                        (query_id, step_name, attempt, step_status, summary, payload,
                         started_at, finished_at)
                    values
                        (:query_id, :stage, :attempt, :status, :summary, cast(:payload as jsonb),
                         now(), case when :is_running then null else now() end)
                    on conflict (query_id, step_name, attempt) do update set
                        step_status = excluded.step_status,
                        summary = excluded.summary,
                        payload = excluded.payload,
                        finished_at = excluded.finished_at
                    """
                ),
                {
                    "query_id": str(query_id),
                    "stage": stage,
                    "attempt": attempt,
                    "status": status,
                    "is_running": status == "running",
                    "summary": summary,
                    "payload": json.dumps(payload, ensure_ascii=False),
                },
            )
            connection.execute(
                text(
                    """
                    update agent.query_runs
                    set current_stage = :stage,
                        status = coalesce(:run_status, status),
                        updated_at = now()
                    where query_id = :query_id
                    """
                ),
                {
                    "query_id": str(query_id),
                    "stage": stage,
                    "run_status": run_status,
                },
            )
        return QueryEvent(
            event_id=row["event_id"],
            query_id=query_id,
            type=event_type,
            stage=stage,
            status=status,
            attempt=attempt,
            summary=summary,
            output=payload,
            occurred_at=row["created_at"],
        )

    def store_response(self, query_id: UUID, response: QueryResponse) -> None:
        payload = sanitize_event_payload(response.model_dump(mode="json"))
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    update agent.query_runs
                    set status = :status,
                        final_answer = :answer,
                        final_sql = :sql,
                        retry_count = :retry_count,
                        elapsed_ms = :elapsed_ms,
                        final_response = cast(:response as jsonb),
                        updated_at = now()
                    where query_id = :query_id
                    """
                ),
                {
                    "query_id": str(query_id),
                    "status": response.status,
                    "answer": response.answer,
                    "sql": response.sql,
                    "retry_count": response.retry_count,
                    "elapsed_ms": response.elapsed_ms,
                    "response": json.dumps(payload, ensure_ascii=False),
                },
            )

    def list_events(self, query_id: UUID, after: int = 0) -> list[QueryEvent]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        """
                    select event_id, query_id, event_type, stage_name, step_status,
                           attempt, summary, payload, created_at
                    from agent.query_events
                    where query_id = :query_id and event_id > :after
                    order by event_id
                    """
                    ),
                    {"query_id": str(query_id), "after": after},
                )
                .mappings()
                .all()
            )
        return [self._event_from_row(row) for row in rows]

    def get_run(self, query_id: UUID, include_events: bool = True) -> QueryRunSnapshot | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("select * from agent.query_runs where query_id = :query_id"),
                    {"query_id": str(query_id)},
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return self._snapshot_from_row(row, self.list_events(query_id) if include_events else [])

    def list_runs(
        self, user_id: str, limit: int, offset: int
    ) -> tuple[list[QueryRunSnapshot], int]:
        with self.engine.connect() as connection:
            total = connection.execute(
                text("select count(*) from agent.query_runs where user_id = :user_id"),
                {"user_id": user_id},
            ).scalar_one()
            rows = (
                connection.execute(
                    text(
                        """
                    select * from agent.query_runs
                    where user_id = :user_id
                    order by created_at desc
                    limit :limit offset :offset
                    """
                    ),
                    {"user_id": user_id, "limit": limit, "offset": offset},
                )
                .mappings()
                .all()
            )
        return [self._snapshot_from_row(row, []) for row in rows], int(total)

    def submit_clarifications(
        self, query_id: UUID, answers: dict[str, str]
    ) -> QueryRunSnapshot | None:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text("select * from agent.query_runs where query_id = :query_id for update"),
                    {"query_id": str(query_id)},
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            if row["status"] != "needs_clarification":
                raise ValueError("This query is not waiting for clarification.")
            response = row["final_response"] or {}
            plan = response.get("query_plan") or {}
            allowed = {item.get("field") for item in plan.get("clarifications", [])}
            unknown = set(answers) - allowed
            if unknown:
                raise ValueError(f"Unknown clarification fields: {', '.join(sorted(unknown))}")
            context = dict(row["clarification_context"] or {})
            rounds = list(context.get("rounds") or [])
            rounds.append(answers)
            context["rounds"] = rounds
            connection.execute(
                text(
                    """
                    update agent.query_runs
                    set status = 'queued', current_stage = 'clarification_received',
                        clarification_context = cast(:context as jsonb), updated_at = now()
                    where query_id = :query_id
                    """
                ),
                {
                    "query_id": str(query_id),
                    "context": json.dumps(context, ensure_ascii=False),
                },
            )
        updated = dict(row)
        updated["status"] = "queued"
        updated["current_stage"] = "clarification_received"
        updated["clarification_context"] = context
        return self._snapshot_from_row(updated, [])

    def mark_interrupted(self) -> None:
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        update agent.query_runs
                        set status = 'interrupted', error_type = 'server_restarted',
                            error_message = '服务重启导致运行中断，可重新运行该查询。',
                            updated_at = now()
                        where status in ('queued', 'running')
                        """
                    )
                )
        except Exception:
            return

    def _run_status(self, event_type: str, step_status: str) -> str | None:
        if event_type == "run.created" or step_status == "running":
            return "running"
        if event_type == "clarification.required":
            return "needs_clarification"
        if event_type == "run.completed":
            return "completed"
        if event_type == "run.failed":
            return "failed"
        return None

    def _event_from_row(self, row: Any) -> QueryEvent:
        return QueryEvent(
            event_id=row["event_id"],
            query_id=row["query_id"],
            type=row["event_type"],
            stage=row["stage_name"],
            status=row["step_status"],
            attempt=row["attempt"],
            summary=row["summary"],
            output=dict(row["payload"] or {}),
            occurred_at=row["created_at"],
        )

    def _snapshot_from_row(self, row: Any, events: list[QueryEvent]) -> QueryRunSnapshot:
        raw_response = row["final_response"]
        response = QueryResponse.model_validate(raw_response) if raw_response else None
        return QueryRunSnapshot(
            query_id=row["query_id"],
            user_id=row["user_id"],
            question=row["question"],
            status=row["status"],
            current_stage=row["current_stage"],
            retry_count=row["retry_count"],
            elapsed_ms=row["elapsed_ms"],
            error_type=row["error_type"],
            error_message=row["error_message"],
            clarification_context=dict(row["clarification_context"] or {}),
            response=response,
            events=events,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
