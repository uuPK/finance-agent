"""Route integration tests use stage doubles; production never substitutes model actors."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.agents.llm_plan_critic import LLMPlanCriticResult
from app.agents.llm_query_plan_actor import QueryPlanBuildResult
from app.agents.llm_result_critic import LLMResultCriticResult
from app.agents.llm_sql_actor import SQLBuildResult
from app.agents.llm_sql_critic import LLMSQLCriticResult
from app.guardrails.result_validator import ResultValidationResult
from app.schemas.query_plan import QueryPlan
from app.schemas.review import ReviewBundle, ReviewDecision
from app.schemas.sql import SQLDraft
from app.schemas.v2_protocol import MissingContextRequest
from app.services.harness_state import HarnessState
from app.services.query_harness import QueryHarness
from app.services.query_service import QueryService
from app.services.sql_executor import SQLExecutionResult


def _context(columns: list[str]) -> dict[str, object]:
    return {
        "source": "database",
        "table_allowlist": ["sales"],
        "allowed_columns_by_table": {"sales": columns},
        "context_stats": {"retrieval_calls": 1, "context_expansion_count": 0},
        "context_bundle": {"item_ids": ["table:mart.sales"]},
    }


def _service(
    drafts: list[SQLDraft],
    results: list[SQLExecutionResult],
    *,
    provider: object | None = None,
    context_request: MissingContextRequest | None = None,
) -> tuple[QueryService, QueryHarness, list[int], list[int], list[dict]]:
    events: list[dict] = []

    async def sink(event: dict) -> None:
        events.append(event)

    service = QueryService(enable_llm=False, event_sink=sink)
    service.settings = service.settings.model_copy(update={"sql_execution_backoff_ms": 0})
    if provider is not None:
        service.schema_context_provider = provider
    service.audit_logger = SimpleNamespace(
        log_sql_execution=lambda **kwargs: None,
        log_result_validation=lambda **kwargs: None,
    )
    actor_attempts: list[int] = []
    review_attempts: list[int] = []
    actor_drafts = iter(drafts)
    execution_results = iter(results)

    async def build(**kwargs: object) -> SQLBuildResult:
        attempt = int(kwargs.get("repair_attempt", 0))
        actor_attempts.append(attempt)
        return SQLBuildResult(draft=next(actor_drafts), source="llm", repair_attempt=attempt)

    async def review_sql(
        query_plan: QueryPlan,
        draft: SQLDraft,
        metadata_context: dict[str, object],
        attempt: int = 0,
    ) -> tuple[ReviewBundle, bool, LLMSQLCriticResult]:
        review_attempts.append(attempt)
        if context_request is not None and len(review_attempts) == 1:
            decision = ReviewDecision(
                passed=False,
                score=0,
                stage="sql_review",
                error_type="missing_context",
                reason="Required metadata is absent.",
                missing_context_request=context_request,
                confidence=1.0,
            )
            return (
                ReviewBundle(llm_checks=[decision]),
                True,
                LLMSQLCriticResult(status="reviewed", decision=decision),
            )
        decision = ReviewDecision(
            passed=True,
            score=100,
            stage="sql_review",
            reason="Approved.",
            confidence=1.0,
        )
        return (
            ReviewBundle(llm_checks=[decision]),
            True,
            LLMSQLCriticResult(status="reviewed", decision=decision),
        )

    async def review_result(
        **kwargs: object,
    ) -> tuple[ResultValidationResult, LLMResultCriticResult]:
        result = kwargs["execution_result"]
        assert isinstance(result, SQLExecutionResult)
        return ResultValidationResult(passed=result.status == "success"), LLMResultCriticResult(
            status="skipped"
        )

    service.sql_actor = SimpleNamespace(build=build)
    service.sql_executor = SimpleNamespace(execute=lambda sql: next(execution_results))
    service._review_sql_draft = review_sql
    service._validate_execution_result = lambda **kwargs: ResultValidationResult(
        passed=kwargs["execution_result"].status == "success"
    )
    service._review_result = review_result
    state = HarnessState(
        uuid4(),
        0,
        max_plan_repairs=1,
        max_sql_repairs=2,
        max_context_refreshes=2,
        max_metadata_refreshes=1,
        max_execution_retries=2,
    )
    service.harness_state = state
    return service, QueryHarness(service, state), actor_attempts, review_attempts, events


def test_transient_execution_retry_reuses_approved_sql_without_model_review() -> None:
    sql = "select id from mart.sales limit 1"
    service, harness, actor_attempts, review_attempts, events = _service(
        [SQLDraft(sql=sql, tables=["mart.sales"])],
        [
            SQLExecutionResult(
                status="failed", sql=sql, error_type="transient_db_error", sqlstate="08006"
            ),
            SQLExecutionResult(
                status="success", sql=sql, columns=["id"], rows=[{"id": 1}], row_count=1
            ),
        ],
    )

    result = asyncio.run(
        harness.run_sql(uuid4(), "Find one sale", QueryPlan(plan_status="ready"), _context(["id"]))
    )

    assert result.passed
    assert actor_attempts == [0]
    assert review_attempts == [0]
    assert harness.state.execution_retries_used == 1
    assert [
        event["output"]["final_action"] for event in events if event["type"] == "route.decided"
    ] == ["RETRY_EXECUTION"]
    assert [
        event["output"]["outcome"] for event in events if event["type"] == "route.executed"
    ] == ["succeeded"]
    assert service.harness_state is harness.state


def test_stale_metadata_refresh_rebuilds_sql_from_live_snapshot() -> None:
    stale_sql = "select old_col from mart.sales limit 1"
    repaired_sql = "select id from mart.sales limit 1"
    provider = SimpleNamespace(
        physical_column_exists=lambda table, column: False,
        load=lambda **kwargs: _context(["id"]),
    )
    service, harness, actor_attempts, review_attempts, events = _service(
        [
            SQLDraft(sql=stale_sql, tables=["mart.sales"]),
            SQLDraft(sql=repaired_sql, tables=["mart.sales"]),
        ],
        [
            SQLExecutionResult(
                status="failed",
                sql=stale_sql,
                error_type="column_not_found",
                sqlstate="42703",
                missing_column="old_col",
            ),
            SQLExecutionResult(
                status="success", sql=repaired_sql, columns=["id"], rows=[{"id": 1}], row_count=1
            ),
        ],
        provider=provider,
    )
    service.llm_enabled = True  # Exercise the real actor route with a test-only stage double.

    result = asyncio.run(
        harness.run_sql(
            uuid4(), "Find one sale", QueryPlan(plan_status="ready"), _context(["id", "old_col"])
        )
    )

    assert result.passed
    assert actor_attempts == [0, 1]
    assert review_attempts == [0, 1]
    assert harness.state.metadata_refreshes_used == harness.state.sql_repairs_used == 1
    assert result.metadata_context["allowed_columns_by_table"] == {"sales": ["id"]}
    assert [
        event["output"]["final_action"] for event in events if event["type"] == "route.decided"
    ] == ["METADATA_REFRESH"]


def test_structured_missing_context_request_rechecks_same_sql_after_expansion() -> None:
    sql = "select new_col from mart.sales limit 1"
    request = MissingContextRequest(
        type="column", concept="new_col", from_table="sales", reason="Column description missing"
    )
    provider = SimpleNamespace(
        expand=lambda current, request, **kwargs: {
            **_context(["id", "new_col"]),
            "context_expansion_status": "expanded",
        }
    )
    service, harness, actor_attempts, review_attempts, events = _service(
        [SQLDraft(sql=sql, tables=["mart.sales"])],
        [
            SQLExecutionResult(
                status="success", sql=sql, columns=["new_col"], rows=[{"new_col": 1}], row_count=1
            )
        ],
        provider=provider,
        context_request=request,
    )

    result = asyncio.run(
        harness.run_sql(
            uuid4(), "Find new values", QueryPlan(plan_status="ready"), _context(["id"])
        )
    )

    assert result.passed
    assert actor_attempts == [0]
    assert review_attempts == [0, 1]
    assert harness.state.context_refreshes_used == 1
    assert [
        event["output"]["final_action"] for event in events if event["type"] == "route.decided"
    ] == ["CONTEXT_REFRESH"]


def test_statement_timeout_repairs_sql_with_specific_optimization_feedback() -> None:
    slow_sql = "select id from mart.sales order by id limit 1"
    optimized_sql = "select id from mart.sales limit 1"
    service, harness, actor_attempts, review_attempts, events = _service(
        [
            SQLDraft(sql=slow_sql, tables=["mart.sales"]),
            SQLDraft(sql=optimized_sql, tables=["mart.sales"]),
        ],
        [
            SQLExecutionResult(
                status="timeout", sql=slow_sql, error_type="query_timeout", sqlstate="57014"
            ),
            SQLExecutionResult(
                status="success", sql=optimized_sql, columns=["id"], rows=[{"id": 1}], row_count=1
            ),
        ],
    )
    service.llm_enabled = True

    result = asyncio.run(
        harness.run_sql(uuid4(), "Find one sale", QueryPlan(plan_status="ready"), _context(["id"]))
    )

    assert result.passed
    assert actor_attempts == [0, 1]
    assert review_attempts == [0, 1]
    assert harness.state.sql_repairs_used == 1
    assert harness.state.execution_retries_used == 0
    assert [
        event["output"]["final_action"] for event in events if event["type"] == "route.decided"
    ] == ["SQL_REPAIR"]
    feedback = next(
        event["output"]["feedback"]
        for event in events
        if event["stage"] == "repair_sql" and event["status"] == "running"
    )
    assert any(item["error_type"] == "query_timeout" for item in feedback)


def test_unchanged_timed_out_sql_stops_without_a_second_execution() -> None:
    sql = "select id from mart.sales order by id limit 1"
    service, harness, actor_attempts, _, events = _service(
        [SQLDraft(sql=sql, tables=["mart.sales"]), SQLDraft(sql=sql, tables=["mart.sales"])],
        [SQLExecutionResult(status="timeout", sql=sql, error_type="query_timeout")],
    )
    service.llm_enabled = True

    result = asyncio.run(
        harness.run_sql(uuid4(), "Find one sale", QueryPlan(plan_status="ready"), _context(["id"]))
    )

    assert not result.passed
    assert result.failure_reason == "SQL optimization returned the same timed-out query."
    assert actor_attempts == [0, 1]
    assert len(result.execution_history or []) == 1
    assert [
        event["output"]["outcome"] for event in events if event["type"] == "route.executed"
    ] == ["failed"]


def test_transient_retry_budget_terminates_after_bounded_executions() -> None:
    sql = "select id from mart.sales limit 1"
    service, harness, actor_attempts, review_attempts, events = _service(
        [SQLDraft(sql=sql, tables=["mart.sales"])],
        [
            SQLExecutionResult(
                status="failed", sql=sql, error_type="transient_db_error", sqlstate="08006"
            )
            for _ in range(3)
        ],
    )

    result = asyncio.run(
        harness.run_sql(uuid4(), "Find one sale", QueryPlan(plan_status="ready"), _context(["id"]))
    )

    assert not result.passed
    assert actor_attempts == [0]
    assert review_attempts == [0]
    assert harness.state.execution_retries_used == 2
    assert len(result.execution_history or []) == 3
    decisions = [event["output"] for event in events if event["type"] == "route.decided"]
    assert [item["final_action"] for item in decisions] == [
        "RETRY_EXECUTION",
        "RETRY_EXECUTION",
        "TERMINATE",
    ]
    assert decisions[-1]["reason_code"] == "budget_exhausted"
    assert any(event["type"] == "budget.exhausted" for event in events)


def test_plan_missing_context_refreshes_then_rechecks_without_rebuilding_plan() -> None:
    initial = _context(["id"])
    expanded = {**_context(["id", "new_col"]), "context_expansion_status": "expanded"}
    request = MissingContextRequest(
        type="column", concept="new_col", from_table="sales", reason="Metric source missing"
    )
    events: list[dict] = []

    async def sink(event: dict) -> None:
        events.append(event)

    service = QueryService(enable_llm=False, event_sink=sink)
    service.schema_context_provider = SimpleNamespace(
        expand=lambda current, request, **kwargs: expanded
    )
    service._load_metadata_context = lambda *args, **kwargs: initial
    service._ground_plan_with_context = lambda question, plan, context: (plan, context)
    service._apply_rule_plan_safeguards = lambda result, deterministic: result
    plan = QueryPlan(plan_status="ready", intent="metadata_question")
    actor_attempts: list[int] = []

    async def build_plan(*args: object, **kwargs: object) -> QueryPlanBuildResult:
        actor_attempts.append(int(kwargs.get("repair_attempt", 0)))
        return QueryPlanBuildResult(plan=plan, source="llm")

    service.query_plan_actor = SimpleNamespace(build=build_plan)
    service.rule_based_actor = SimpleNamespace(build=lambda question: plan)
    review_attempts: list[int] = []

    async def review_plan(
        plan: QueryPlan,
        context: dict[str, object],
        *,
        attempt: int,
        original_question: str,
    ) -> tuple[ReviewBundle, bool, LLMPlanCriticResult]:
        review_attempts.append(attempt)
        approved = context is expanded
        decision = ReviewDecision(
            passed=approved,
            score=100 if approved else 0,
            stage="query_plan_review",
            error_type=None if approved else "missing_context",
            reason="Approved" if approved else "Missing metric source",
            missing_context_request=None if approved else request,
            confidence=1.0,
        )
        return (
            ReviewBundle(llm_checks=[decision]),
            True,
            LLMPlanCriticResult(status="reviewed", decision=decision),
        )

    service._review_query_plan = review_plan
    state = HarnessState(uuid4(), 0, max_plan_repairs=1, max_sql_repairs=1)
    service.harness_state = state
    phase = asyncio.run(QueryHarness(service, state).prepare_plan("Find new values"))

    assert phase.review_bundle.passed
    assert actor_attempts == [0]
    assert review_attempts == [0, 1]
    assert state.context_refreshes_used == 1
    assert phase.metadata_context is expanded
    assert [
        event["output"]["final_action"] for event in events if event["type"] == "route.decided"
    ] == ["CONTEXT_REFRESH"]
