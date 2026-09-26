from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.agents.answer_actor import AnswerActor
from app.agents.llm_plan_critic import LLMPlanCriticResult
from app.agents.llm_query_plan_actor import QueryPlanBuildResult
from app.agents.llm_result_critic import LLMResultCriticResult
from app.agents.llm_sql_actor import SQLBuildResult
from app.agents.llm_sql_critic import LLMSQLCriticResult
from app.db.session import engine
from app.guardrails.empty_result_diagnostic import EmptyResultDiagnosticValidator
from app.guardrails.result_validator import ResultValidationResult
from app.schemas.query import EmptyResultDiagnosis, QueryRequest, QueryResponse
from app.schemas.query_plan import QueryPlan
from app.schemas.review import ReviewBundle
from app.schemas.sql import SQLDraft
from app.services.harness_state import HarnessState
from app.services.query_harness import PlanPhaseResult, QueryHarness
from app.services.query_service import QueryService, SQLLoopResult
from app.services.sql_executor import SQLExecutionResult

_CONTEXT = {
    "source": "database",
    "table_allowlist": ["sales"],
    "allowed_columns_by_table": {"sales": ["id", "a", "b", "c"]},
}


@dataclass
class _ProbeExecutor:
    counts: dict[str, int] | None
    calls: list[str] = field(default_factory=list)

    def execute(self, sql: str) -> SQLExecutionResult:
        self.calls.append(sql)
        if self.counts is None:
            return SQLExecutionResult(status="timeout", sql=sql, error_type="query_timeout")
        return SQLExecutionResult(
            status="success",
            sql=sql,
            columns=list(self.counts),
            rows=[self.counts],
            row_count=1,
        )


def test_three_and_predicates_are_checked_in_one_guarded_read_only_probe() -> None:
    executor = _ProbeExecutor(
        {
            "individual_1": 7,
            "individual_2": 9,
            "individual_3": 3,
            "prefix_2": 2,
            "prefix_3": 0,
        }
    )
    diagnostic = EmptyResultDiagnosticValidator(executor=executor)

    result = diagnostic.diagnose(
        "select id from mart.sales as s where s.a = 1 and s.b > 2 and s.c in (3, 4) limit 10",
        _CONTEXT,
    )

    assert result.status == "plausible_valid_empty"
    assert result.reason_code == "combination_empty"
    assert result.individual_nonempty == [True, True, True]
    assert result.prefix_nonempty == [True, False]
    assert len(executor.calls) == 1
    assert executor.calls[0].count("COUNT(*) FILTER") == 5
    assert "FROM mart.sales AS s" in executor.calls[0]
    assert "LIMIT" not in executor.calls[0]


def test_single_condition_without_matches_is_diagnosed_but_not_repaired() -> None:
    executor = _ProbeExecutor({"individual_1": 8, "individual_2": 0, "prefix_2": 0})
    result = EmptyResultDiagnosticValidator(executor=executor).diagnose(
        "select id from mart.sales where a = 1 and b = 2 limit 10", _CONTEXT
    )

    assert result.status == "predicate_empty"
    assert result.individual_nonempty == [True, False]
    assert len(executor.calls) == 1


@pytest.mark.parametrize(
    ("counts", "reason_code"),
    [
        (
            {
                "individual_1": 5,
                "individual_2": 5,
                "individual_3": 5,
                "prefix_2": 0,
                "prefix_3": 0,
            },
            "earlier_intersection_empty",
        ),
        (
            {
                "individual_1": 5,
                "individual_2": 5,
                "individual_3": 5,
                "prefix_2": 3,
                "prefix_3": 2,
            },
            "full_filter_mismatch",
        ),
    ],
)
def test_ambiguous_intersections_do_not_claim_valid_combination_empty(
    counts: dict[str, int], reason_code: str
) -> None:
    result = EmptyResultDiagnosticValidator(executor=_ProbeExecutor(counts)).diagnose(
        "select id from mart.sales where a = 1 and b = 2 and c = 3 limit 10", _CONTEXT
    )
    assert result.status == "inconclusive"
    assert result.reason_code == reason_code


@pytest.mark.parametrize(
    "sql",
    [
        "select id from mart.sales where a = 1 or b = 2 limit 10",
        "select id from mart.sales where a = 1 and b = 2",
        "select id from mart.sales where a = 1 limit 10",
        "select id from mart.sales where a = 1 and b = 2 and c = 3 and id = 4 limit 10",
        "select id from mart.sales where a = 1 and b = 2 limit 10 offset 10",
        "select s.id from mart.sales s join mart.other o on s.id = o.id "
        "where s.a = 1 and s.b = 2 limit 10",
        "select id from mart.sales where a = 1 and unknown_column = 2 limit 10",
        "select id from mart.sales where random() > 0.5 and b = 2 limit 10",
    ],
)
def test_complex_or_unverified_sql_never_launches_diagnostic_probe(sql: str) -> None:
    executor = _ProbeExecutor({})
    result = EmptyResultDiagnosticValidator(executor=executor).diagnose(sql, _CONTEXT)

    assert result.status == "unsupported"
    assert executor.calls == []


def test_probe_failure_does_not_convert_empty_result_into_sql_error() -> None:
    executor = _ProbeExecutor(None)
    result = EmptyResultDiagnosticValidator(executor=executor).diagnose(
        "select id from mart.sales where a = 1 and b = 2 limit 10", _CONTEXT
    )

    assert result.status == "probe_failed"
    assert result.reason_code == "probe_execution_failed"
    assert len(executor.calls) == 1


def test_empty_result_has_independent_response_status_and_cautious_answer() -> None:
    diagnosis = EmptyResultDiagnosis(
        status="plausible_valid_empty",
        reason_code="combination_empty",
        predicate_count=2,
        individual_nonempty=[True, True],
        prefix_nonempty=[False],
    )
    response = QueryResponse(
        status="completed",
        result_status="EMPTY_RESULT",
        empty_result_diagnosis=diagnosis,
        answer="当前条件组合下没有符合条件的数据。",
    )
    assert response.model_dump(mode="json")["result_status"] == "EMPTY_RESULT"
    assert (
        AnswerActor()
        .render(
            question="筛选数据",
            query_plan=QueryPlan(plan_status="ready"),
            execution_result=SQLExecutionResult(
                status="success", sql="select id from mart.sales limit 10", columns=["id"]
            ),
            preview_rows=[],
            empty_result_diagnosis=diagnosis,
        )
        .answer
        == "当前条件组合下没有符合条件的数据。"
    )


def test_query_service_keeps_completed_run_and_exposes_empty_result_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnosis = EmptyResultDiagnosis(
        status="plausible_valid_empty",
        reason_code="combination_empty",
        predicate_count=2,
        individual_nonempty=[True, True],
        prefix_nonempty=[False],
    )
    plan = QueryPlan(plan_status="ready")
    context = {**_CONTEXT, "source": "database", "table_count": 1}
    plan_build = QueryPlanBuildResult(plan=plan, source="llm")
    sql = "select id from mart.sales where a = 1 and b = 2 limit 10"
    sql_build = SQLBuildResult(draft=SQLDraft(sql=sql, tables=["mart.sales"]), source="llm")
    execution = SQLExecutionResult(status="success", sql=sql, columns=["id"])
    validation = ResultValidationResult(passed=True)

    async def prepare_plan(
        self: QueryHarness, question: str, previous_plan: object = None
    ) -> PlanPhaseResult:
        return PlanPhaseResult(
            query_plan=plan,
            metadata_context=context,
            build_result=plan_build,
            build_results=[plan_build],
            review_bundle=ReviewBundle(),
            hard_review_passed=True,
            critic_result=LLMPlanCriticResult(status="skipped"),
            review_history=[],
        )

    async def run_sql(self: QueryHarness, *args: object) -> SQLLoopResult:
        return SQLLoopResult(
            sql=sql,
            passed=True,
            build_results=[sql_build],
            review_bundle=ReviewBundle(),
            hard_review_passed=True,
            critic_result=LLMSQLCriticResult(status="skipped"),
            review_history=[],
            repair_count=0,
            metadata_context=context,
            execution_result=execution,
            result_hard_validation=validation,
            result_validation=validation,
            result_critic_result=LLMResultCriticResult(status="skipped"),
            empty_result_diagnosis=diagnosis,
        )

    monkeypatch.setattr(QueryHarness, "prepare_plan", prepare_plan)
    monkeypatch.setattr(QueryHarness, "run_sql", run_sql)
    service = QueryService(enable_llm=False)
    service.audit_logger = SimpleNamespace(finish_query_run=lambda **kwargs: None)
    response = asyncio.run(
        service.run(QueryRequest(question="Find matching sales"), start_audit=False)
    )

    assert response.status == "completed"
    assert response.result_status == "EMPTY_RESULT"
    assert response.empty_result_diagnosis == diagnosis
    assert response.answer == "当前条件组合下没有符合条件的数据。"
    assert response.sql == sql
    assert response.result_preview == []
    assert any(step.name == "diagnose_empty_result" for step in response.steps)


def test_sql_loop_diagnoses_empty_result_without_regenerating_sql() -> None:
    sql = "select id from mart.sales where a = 1 and b = 2 limit 10"
    events: list[dict] = []

    async def sink(event: dict) -> None:
        events.append(event)

    service = QueryService(enable_llm=False, event_sink=sink)
    service.audit_logger = SimpleNamespace(
        log_sql_execution=lambda **kwargs: None,
        log_result_validation=lambda **kwargs: None,
    )
    actor_calls: list[int] = []

    async def build_sql(**kwargs: object) -> SQLBuildResult:
        actor_calls.append(int(kwargs.get("repair_attempt", 0)))
        return SQLBuildResult(draft=SQLDraft(sql=sql, tables=["mart.sales"]), source="llm")

    async def review_sql(*args: object, **kwargs: object) -> tuple:
        return ReviewBundle(), True, LLMSQLCriticResult(status="skipped")

    async def review_result(**kwargs: object) -> tuple:
        return kwargs["hard_validation"], LLMResultCriticResult(status="skipped")

    diagnosis = EmptyResultDiagnosis(
        status="plausible_valid_empty",
        reason_code="combination_empty",
        predicate_count=2,
        individual_nonempty=[True, True],
        prefix_nonempty=[False],
    )
    service.sql_actor = SimpleNamespace(build=build_sql)
    service.sql_executor = SimpleNamespace(
        execute=lambda query: SQLExecutionResult(status="success", sql=query, columns=["id"])
    )
    service.empty_result_validator = SimpleNamespace(diagnose=lambda query, context: diagnosis)
    service._review_sql_draft = review_sql
    service._review_result = review_result
    state = HarnessState(uuid4(), 0, max_plan_repairs=1, max_sql_repairs=1)
    service.harness_state = state

    loop = asyncio.run(
        QueryHarness(service, state).run_sql(
            uuid4(),
            "Find matching sales",
            QueryPlan(plan_status="ready"),
            {**_CONTEXT, "source": "database", "table_count": 1},
        )
    )

    assert loop.passed
    assert loop.empty_result_diagnosis == diagnosis
    assert actor_calls == [0]
    assert state.sql_repairs_used == 0
    assert not any(event["type"] == "route.decided" for event in events)
    trace = next(event for event in events if event["type"] == "trace.empty_result_diagnosis")
    assert trace["output"]["status"] == "plausible_valid_empty"
    assert "sql" not in trace["output"]
    assert "counts" not in trace["output"]


@pytest.mark.skipif(
    os.getenv("RUN_TRACE_DB_TESTS") != "1", reason="requires local seeded PostgreSQL"
)
def test_real_postgres_probe_confirms_final_intersection_is_empty() -> None:
    with engine.connect() as connection:
        values = [
            row[0]
            for row in connection.execute(
                text(
                    "select cust_status from mart.ads_cust_info_d "
                    "where cust_status is not null and cust_age >= 0 "
                    "group by cust_status order by cust_status limit 2"
                )
            ).all()
        ]
        columns = [
            row[0]
            for row in connection.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_schema = 'mart' and table_name = 'ads_cust_info_d'"
                )
            ).all()
        ]
    if len(values) < 2:
        pytest.skip("Seed data has fewer than two distinct customer statuses")
    quoted = ["'" + value.replace("'", "''") + "'" for value in values]
    sql = (
        "select cust_status from mart.ads_cust_info_d "
        f"where cust_status = {quoted[0]} and cust_age >= 0 "
        f"and cust_status = {quoted[1]} limit 10"
    )
    result = EmptyResultDiagnosticValidator().diagnose(
        sql,
        {
            "source": "database",
            "table_allowlist": ["ads_cust_info_d"],
            "allowed_columns_by_table": {"ads_cust_info_d": columns},
        },
    )
    assert result.status == "plausible_valid_empty"
    assert result.individual_nonempty == [True, True, True]
    assert result.prefix_nonempty == [True, False]
