from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from app.schemas.run import QueryEvent
from app.schemas.trace import TraceEvent
from app.services.harness_state import HarnessState
from app.services.query_service import QueryService
from app.services.run_repository import RunRepository


def test_trace_event_validates_coordinates_and_duration() -> None:
    event = TraceEvent(
        query_id=uuid4(),
        stage="sql_generation",
        type="stage.completed",
        status="passed",
        summary="done",
        clarification_round=1,
        stage_attempt=2,
    )
    assert event.schema_version == 2
    assert (event.clarification_round, event.stage_attempt) == (1, 2)
    assert event.duration_ms is None

    for invalid in ({"clarification_round": -1}, {"stage_attempt": -1}, {"duration_ms": -1}):
        with pytest.raises(ValidationError):
            TraceEvent(
                query_id=uuid4(),
                stage="sql_generation",
                type="stage.completed",
                status="passed",
                summary="done",
                **invalid,
            )


def test_legacy_query_event_remains_readable() -> None:
    event = QueryEvent.model_validate(
        {
            "event_id": 1,
            "query_id": str(uuid4()),
            "type": "stage.completed",
            "stage": "sql_generation",
            "status": "passed",
            "attempt": 1,
            "summary": "done",
            "output": {},
            "occurred_at": datetime.now(UTC),
        }
    )
    assert event.schema_version == 1
    assert event.attempt == 1
    assert event.clarification_round is None
    assert event.stage_attempt is None
    assert event.model_dump()["attempt"] == 1


def test_query_service_emits_round_and_stage_attempt_separately() -> None:
    events: list[dict] = []

    async def sink(event: dict) -> None:
        events.append(event)

    service = QueryService(enable_llm=False, event_sink=sink, event_attempt=1)
    asyncio.run(service._emit("sql_generation", "running", "start", attempt=0))
    asyncio.run(service._emit("sql_generation", "passed", "repaired", attempt=1))

    assert [(e["clarification_round"], e["stage_attempt"]) for e in events] == [(1, 0), (1, 1)]
    assert [e["attempt"] for e in events] == [1, 2]  # Legacy SSE field remains.


def test_direct_recorder_telemetry_updates_harness_state() -> None:
    events: list[dict] = []

    async def sink(event: dict) -> None:
        events.append(event)

    service = QueryService(enable_llm=False, event_sink=sink)
    state = HarnessState(uuid4(), clarification_round=0, max_plan_repairs=2, max_sql_repairs=2)
    service.harness_state = state

    async def record() -> None:
        await service._emit("build_query_plan", "running", "start")
        await service.trace_recorder.record(
            "llm_call", {"prompt_tokens": 42, "completion_tokens": 7}
        )
        await service._emit("build_query_plan", "passed", "done")

    asyncio.run(record())
    assert [event["type"] for event in events] == [
        "stage.started", "trace.llm_call", "stage.completed"
    ]
    assert state.llm_calls == 1
    assert state.prompt_tokens == 42
    assert state.completion_tokens == 7
    assert state.stages[("build_query_plan", 0)].span_id == events[0]["span_id"]


@pytest.mark.skipif(
    os.getenv("RUN_TRACE_DB_TESTS") != "1",
    reason="requires local PostgreSQL with schema.sql or migration 011 applied",
)
def test_repair_and_clarification_round_do_not_overwrite_each_other() -> None:
    repository = RunRepository()
    query_id = uuid4()
    repository.create_run(query_id, "trace collision regression", "trace-test")
    try:
        with repository.engine.begin() as connection:
            connection.execute(
                text("""
                    insert into agent.query_events
                        (query_id, event_type, stage_name, step_status, attempt,
                         schema_version, clarification_round, stage_attempt, summary)
                    values (:query_id, 'stage.completed', 'sql_generation', 'passed',
                            1, 1, null, null, 'legacy')
                """),
                {"query_id": str(query_id)},
            )
            connection.execute(
                text("""
                    insert into agent.query_steps
                        (query_id, step_name, step_status, attempt, schema_version,
                         clarification_round, stage_attempt, summary)
                    values (:query_id, 'sql_generation', 'passed', 1, 1,
                            null, null, 'legacy')
                """),
                {"query_id": str(query_id)},
            )
        repaired = repository.append_event(
            query_id,
            "stage.completed",
            "sql_generation",
            "passed",
            "repair",
            attempt=1,
            clarification_round=0,
            stage_attempt=1,
        )
        resumed = repository.append_event(
            query_id,
            "stage.completed",
            "sql_generation",
            "passed",
            "resumed",
            attempt=1,
            clarification_round=1,
            stage_attempt=0,
        )
        assert repaired.attempt == resumed.attempt == 1
        assert (repaired.clarification_round, repaired.stage_attempt) == (0, 1)
        assert (resumed.clarification_round, resumed.stage_attempt) == (1, 0)
        events = repository.list_events(query_id)
        assert [event.summary for event in events] == ["legacy", "repair", "resumed"]
        assert events[0].schema_version == 1
        assert events[0].clarification_round is None
        assert events[0].stage_attempt is None
        with repository.engine.connect() as connection:
            steps = connection.execute(
                text("""
                    select schema_version, clarification_round, stage_attempt, summary
                    from agent.query_steps where query_id = :query_id
                    order by schema_version, clarification_round, stage_attempt
                """),
                {"query_id": str(query_id)},
            ).all()
        assert steps == [
            (1, None, None, "legacy"),
            (2, 0, 1, "repair"),
            (2, 1, 0, "resumed"),
        ]
    finally:
        with repository.engine.begin() as connection:
            connection.execute(
                text("delete from agent.query_runs where query_id = :query_id"),
                {"query_id": str(query_id)},
            )


@pytest.mark.skipif(
    os.getenv("RUN_TRACE_DB_TESTS") != "1",
    reason="requires local PostgreSQL with schema.sql or migration 011 applied",
)
def test_trace_telemetry_is_append_only_and_does_not_replace_stage_view() -> None:
    repository = RunRepository()
    query_id = uuid4()
    repository.create_run(query_id, "trace telemetry regression", "trace-test")
    try:
        started = repository.append_event(
            query_id, "stage.started", "generate_sql", "running", "stage started",
            span_id=uuid4(),
        )
        telemetry = repository.append_event(
            query_id, "trace.llm_call", "generate_sql", "passed", "llm_call",
            {"prompt_tokens": 12, "completion_tokens": 4},
            span_id=uuid4(), parent_span_id=started.span_id,
        )
        assert telemetry.parent_span_id == started.span_id
        with repository.engine.connect() as connection:
            step_rows = connection.execute(
                text("""
                    select summary from agent.query_steps
                    where query_id = :query_id and step_name = 'generate_sql'
                """),
                {"query_id": str(query_id)},
            ).all()
            run_stage = connection.execute(
                text("select current_stage from agent.query_runs where query_id = :query_id"),
                {"query_id": str(query_id)},
            ).scalar_one()
        assert step_rows == [("stage started",)]
        assert run_stage == "generate_sql"
        assert [event.type for event in repository.list_events(query_id)] == [
            "stage.started", "trace.llm_call"
        ]
    finally:
        with repository.engine.begin() as connection:
            connection.execute(
                text("delete from agent.query_runs where query_id = :query_id"),
                {"query_id": str(query_id)},
            )
