from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.schemas.sql import SQLDraft
from app.schemas.v2_protocol import FailureEvent, HarnessAction
from app.services.failure_router import FailureRouter, classify_unknown_column
from app.services.harness_state import HarnessState
from app.services.query_harness import QueryHarness
from app.services.query_service import QueryService
from app.services.sql_executor import SQLExecutionResult, SQLExecutor


def test_failure_router_maps_only_explicitly_supported_failure_domains() -> None:
    router = FailureRouter()
    cases = [
        (
            FailureEvent(stage="plan", error_type="wrong_grain", retryable=True),
            HarnessAction.PLAN_REPAIR,
        ),
        (
            FailureEvent(stage="sql", error_type="missing_time_filter", retryable=True),
            HarnessAction.SQL_REPAIR,
        ),
        (
            FailureEvent(stage="execution", error_type="sql_syntax_error", retryable=True),
            HarnessAction.SQL_REPAIR,
        ),
        (
            FailureEvent(stage="execution", error_type="unknown_column_in_sql", retryable=True),
            HarnessAction.SQL_REPAIR,
        ),
        (
            FailureEvent(stage="execution", error_type="missing_metadata_context", retryable=True),
            HarnessAction.CONTEXT_REFRESH,
        ),
        (
            FailureEvent(stage="execution", error_type="stale_metadata_schema", retryable=True),
            HarnessAction.METADATA_REFRESH,
        ),
        (
            FailureEvent(stage="execution", error_type="transient_db_error", retryable=True),
            HarnessAction.RETRY_EXECUTION,
        ),
        (
            FailureEvent(stage="execution", error_type="lock_timeout", retryable=True),
            HarnessAction.RETRY_EXECUTION,
        ),
        (
            FailureEvent(stage="execution", error_type="query_timeout", retryable=True),
            HarnessAction.SQL_REPAIR,
        ),
        (
            FailureEvent(stage="execution", error_type="query_cancelled", retryable=True),
            HarnessAction.TERMINATE,
        ),
        (
            FailureEvent(stage="execution", error_type="column_not_found", retryable=True),
            HarnessAction.TERMINATE,
        ),
        (
            FailureEvent(stage="execution", error_type="timeout", retryable=True),
            HarnessAction.TERMINATE,
        ),
        (
            FailureEvent(stage="retrieval", error_type="missing_context", retryable=True),
            HarnessAction.CONTEXT_REFRESH,
        ),
        (
            FailureEvent(stage="plan", error_type="invalid_plan", retryable=False),
            HarnessAction.TERMINATE,
        ),
    ]

    for failure, expected in cases:
        assert router.propose(failure) == expected


def test_unknown_column_classification_requires_live_and_context_evidence() -> None:
    assert classify_unknown_column(live_schema_has_column=True, context_has_column=False) == (
        "missing_metadata_context"
    )
    assert classify_unknown_column(live_schema_has_column=False, context_has_column=True) == (
        "stale_metadata_schema"
    )
    assert classify_unknown_column(live_schema_has_column=False, context_has_column=False) == (
        "unknown_column_in_sql"
    )
    assert classify_unknown_column(live_schema_has_column=None, context_has_column=False) == (
        "column_not_found"
    )


def test_unknown_column_refresh_requires_one_allowlisted_live_table() -> None:
    service = QueryService(enable_llm=False)
    service.schema_context_provider.physical_column_exists = lambda table, column: True
    harness = QueryHarness(
        service,
        HarnessState(uuid4(), 0, max_plan_repairs=1, max_sql_repairs=1),
    )
    execution = SQLExecutionResult(
        status="failed",
        sql="select missing_metric from mart.sales",
        error_type="column_not_found",
        missing_column="missing_metric",
    )
    context = {"table_allowlist": ["sales"], "allowed_columns_by_table": {"sales": ["id"]}}

    classified = harness._classify_unknown_column(
        execution,
        SQLDraft(sql=execution.sql, tables=["mart.sales"]),
        context,
    )
    ambiguous = harness._classify_unknown_column(
        execution,
        SQLDraft(
            sql="select missing_metric from mart.sales join mart.customers on true",
            tables=["mart.sales", "mart.customers"],
        ),
        context,
    )
    unqualified = harness._classify_unknown_column(
        execution,
        SQLDraft(sql="select missing_metric from sales", tables=["sales"]),
        context,
    )

    assert classified == "missing_metadata_context"
    assert ambiguous == "column_not_found"
    assert unqualified == "column_not_found"


def test_sql_executor_extracts_postgres_missing_column_diagnostic() -> None:
    original = SimpleNamespace(
        sqlstate="42703",
        diag=SimpleNamespace(column_name="missing_metric"),
    )
    wrapped = SimpleNamespace(orig=original)

    assert SQLExecutor._sqlstate(wrapped) == "42703"
    assert SQLExecutor._missing_column(wrapped, "unstructured database error") == "missing_metric"
    assert SQLExecutor()._classify_error("localized database diagnostic", "42703") == (
        "column_not_found"
    )


def test_sql_executor_separates_statement_timeout_cancel_and_connection_faults() -> None:
    executor = SQLExecutor()
    assert executor._classify_error("canceling statement due to statement timeout", "57014") == (
        "query_timeout"
    )
    assert executor._classify_error("canceling statement due to user request", "57014") == (
        "query_cancelled"
    )
    assert executor._classify_error("canceling statement due to lock timeout", "55P03") == (
        "lock_timeout"
    )
    assert executor._classify_error("connection failed", "08006") == "transient_db_error"
    assert executor._classify_error("protocol violation", "08P01") == "sql_execution_error"
    assert executor._classify_error("connection lost", connection_invalidated=True) == (
        "transient_db_error"
    )
    assert executor._classify_error("connection refused", operational_error=True) == (
        "transient_db_error"
    )


def test_harness_records_final_route_and_exhausted_budget_without_failure_text() -> None:
    events: list[dict] = []

    async def sink(event: dict) -> None:
        events.append(event)

    service = QueryService(enable_llm=False, event_sink=sink)
    # Exercise routing policy only; no model actor is called by this test.
    service.llm_enabled = True
    state = HarnessState(uuid4(), 0, max_plan_repairs=0, max_sql_repairs=0)
    service.harness_state = state
    harness = QueryHarness(service, state)
    failure = FailureEvent(
        stage="plan",
        error_type="wrong_grain",
        evidence=["sensitive evidence text"],
        repair_hint="private repair hint",
        retryable=True,
    )

    decision = asyncio.run(
        harness.route_failure(
            failure,
            source_stage="query_plan_hard_review",
            source_attempt=0,
        )
    )

    assert decision.candidate_action == HarnessAction.PLAN_REPAIR
    assert decision.final_action == HarnessAction.TERMINATE
    assert decision.reason_code == "budget_exhausted"
    assert state.plan_repairs_used == 0
    assert state.route_count == 1
    assert [event["type"] for event in events] == [
        "route.decided",
        "budget.exhausted",
        "route.executed",
    ]
    route_output = events[0]["output"]
    assert route_output["candidate_action"] == "PLAN_REPAIR"
    assert route_output["final_action"] == "TERMINATE"
    assert route_output["budget"] == {
        "domain": "plan",
        "used": 0,
        "limit": 0,
        "exhausted": True,
        "reserved": False,
    }
    assert "sensitive evidence text" not in str(events)
    assert "private repair hint" not in str(events)


def test_unverified_context_refresh_is_audited_then_terminated() -> None:
    events: list[dict] = []

    async def sink(event: dict) -> None:
        events.append(event)

    service = QueryService(enable_llm=False, event_sink=sink)
    service.llm_enabled = True
    state = HarnessState(uuid4(), 0, max_plan_repairs=1, max_sql_repairs=1)
    service.harness_state = state
    harness = QueryHarness(service, state)
    decision = asyncio.run(
        harness.route_failure(
            FailureEvent(stage="sql", error_type="missing_metadata_context", retryable=True),
            source_stage="sql_hard_review",
            source_attempt=0,
        )
    )

    assert decision.candidate_action == HarnessAction.CONTEXT_REFRESH
    assert decision.final_action == HarnessAction.TERMINATE
    assert decision.reason_code == "context_refresh_evidence_missing"
    assert state.sql_repairs_used == 0
    assert [event["type"] for event in events] == ["route.decided", "route.executed"]
    assert events[0]["output"]["candidate_action"] == "CONTEXT_REFRESH"
    assert events[0]["output"]["final_action"] == "TERMINATE"


def test_verified_context_refresh_reserves_only_context_budget() -> None:
    events: list[dict] = []

    async def sink(event: dict) -> None:
        events.append(event)

    service = QueryService(enable_llm=False, event_sink=sink)
    state = HarnessState(uuid4(), 0, max_plan_repairs=1, max_sql_repairs=1, max_context_refreshes=1)
    service.harness_state = state
    harness = QueryHarness(service, state)
    failure = FailureEvent(stage="execution", error_type="missing_metadata_context", retryable=True)

    decision = asyncio.run(
        harness.route_failure(
            failure,
            source_stage="execute_sql",
            source_attempt=0,
            allow_context_refresh=True,
        )
    )

    assert decision.final_action == HarnessAction.CONTEXT_REFRESH
    assert state.context_refreshes_used == 1
    assert state.sql_repairs_used == 0
    assert [event["type"] for event in events] == ["route.decided"]
    assert events[0]["output"]["budget"] == {
        "domain": "context",
        "used": 1,
        "limit": 1,
        "exhausted": True,
        "reserved": True,
    }


def test_metadata_refresh_reserves_metadata_and_sql_budgets() -> None:
    events: list[dict] = []

    async def sink(event: dict) -> None:
        events.append(event)

    service = QueryService(enable_llm=False, event_sink=sink)
    service.llm_enabled = True  # Routing policy only; no model call is made.
    state = HarnessState(
        uuid4(), 0, max_plan_repairs=1, max_sql_repairs=1, max_metadata_refreshes=1
    )
    service.harness_state = state
    harness = QueryHarness(service, state)
    failure = FailureEvent(stage="execution", error_type="stale_metadata_schema", retryable=True)

    async def decide_twice() -> tuple:
        first = await harness.route_failure(
            failure, source_stage="execute_sql", source_attempt=0, allow_metadata_refresh=True
        )
        second = await harness.route_failure(
            failure, source_stage="execute_sql", source_attempt=0, allow_metadata_refresh=True
        )
        return first, second

    first, second = asyncio.run(decide_twice())
    assert first.final_action == HarnessAction.METADATA_REFRESH
    assert second.final_action == HarnessAction.TERMINATE
    assert second.reason_code == "budget_exhausted"
    assert state.metadata_refreshes_used == 1
    assert state.sql_repairs_used == 0
    assert [event["type"] for event in events] == [
        "route.decided",
        "route.decided",
        "budget.exhausted",
        "route.executed",
    ]


def test_execution_retry_budget_needs_no_model_and_exhausts() -> None:
    service = QueryService(enable_llm=False)
    state = HarnessState(uuid4(), 0, max_plan_repairs=0, max_sql_repairs=0, max_execution_retries=1)
    service.harness_state = state
    harness = QueryHarness(service, state)
    failure = FailureEvent(
        stage="execution", error_type="transient_db_error", retryable=True, sqlstate="08006"
    )

    async def decide_twice() -> tuple:
        first = await harness.route_failure(
            failure, source_stage="execute_sql", source_attempt=0, allow_execution_retry=True
        )
        second = await harness.route_failure(
            failure, source_stage="execute_sql", source_attempt=1, allow_execution_retry=True
        )
        return first, second

    first, second = asyncio.run(decide_twice())
    assert first.final_action == HarnessAction.RETRY_EXECUTION
    assert second.final_action == HarnessAction.TERMINATE
    assert second.reason_code == "budget_exhausted"
    assert state.execution_retries_used == state.total_retries == 1
