from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest

from app.agents.llm_sql_critic import LLMSQLCriticResult
from app.guardrails.sql_plan_inspector import SQLPlanInspection, SQLPlanInspector
from app.schemas.query_plan import QueryPlan
from app.schemas.sql import SQLDraft
from app.services.query_service import QueryService


class _RecordingEngine:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.statements: list[str] = []
        self.rolled_back = False

    def connect(self) -> _RecordingEngine:
        return self

    def __enter__(self) -> _RecordingEngine:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def begin(self) -> _RecordingEngine:
        return self

    def rollback(self) -> None:
        self.rolled_back = True

    def execute(self, statement: object, params: object = None) -> SimpleNamespace:
        self.statements.append(str(statement))
        return SimpleNamespace(scalar_one=lambda: self.payload)


def test_explain_is_read_only_non_analyze_and_advisory() -> None:
    engine = _RecordingEngine(
        [{"Plan": {"Node Type": "Hash Join", "Plan Rows": 50, "Total Cost": 120.0}}]
    )
    result = SQLPlanInspector(engine=engine, timeout_seconds=30).inspect(
        "select a.id from mart.a a join mart.b b on b.id = a.id limit 10"
    )

    assert result.status == "ok"
    assert engine.rolled_back
    assert engine.statements[0] == "SET TRANSACTION READ ONLY"
    assert engine.statements[1].startswith("select set_config('statement_timeout'")
    assert engine.statements[2].lower().startswith("explain (format json) select")
    assert all("ANALYZE" not in statement for statement in engine.statements)
    assert result.facts()["root_plan_rows"] == 50


def test_simple_sql_skips_explain_without_opening_connection() -> None:
    engine = _RecordingEngine([])
    result = SQLPlanInspector(engine=engine).inspect("select id from mart.a limit 10")
    assert result.status == "skipped"
    assert result.reason_code == "simple_sql"
    assert engine.statements == []


def test_plan_estimates_are_flags_not_hard_failures() -> None:
    inspector = SQLPlanInspector(max_plan_rows=100, max_total_cost=500)
    result = inspector._summarize(
        {
            "Node Type": "Nested Loop",
            "Plan Rows": 200,
            "Total Cost": 800.0,
            "Plans": [
                {"Node Type": "Seq Scan", "Plan Rows": 300},
                {"Node Type": "Seq Scan", "Plan Rows": 200},
            ],
        }
    )
    assert result.status == "ok"
    assert set(result.flags) == {
        "estimated_large_scan",
        "estimated_large_join_output",
        "estimated_high_cost",
        "possible_cartesian_join",
    }


def test_parameterized_nested_loop_is_not_called_cartesian() -> None:
    inspector = SQLPlanInspector()
    result = inspector._summarize(
        {
            "Node Type": "Nested Loop",
            "Plan Rows": 10,
            "Total Cost": 100.0,
            "Plans": [
                {"Node Type": "Seq Scan", "Plan Rows": 10},
                {"Node Type": "Index Scan", "Plan Rows": 1, "Index Cond": "(id = a.id)"},
            ],
        }
    )
    assert "possible_cartesian_join" not in result.flags


def test_enabled_explain_failure_does_not_block_sql_critic() -> None:
    events: list[dict] = []

    async def sink(event: dict) -> None:
        events.append(event)

    service = QueryService(enable_llm=False, event_sink=sink)
    service.settings = service.settings.model_copy(update={"enable_sql_explain_check": True})
    service.sql_plan_inspector = SimpleNamespace(
        inspect=lambda sql: SQLPlanInspection("failed", "explain_unavailable")
    )
    critic_calls: list[bool] = []

    async def review(**kwargs: object) -> LLMSQLCriticResult:
        critic_calls.append(True)
        return LLMSQLCriticResult(status="skipped")

    service.sql_critic = SimpleNamespace(review=review)
    context = {
        "source": "database",
        "table_allowlist": ["a", "b"],
        "allowed_columns_by_table": {"a": ["id"], "b": ["id"]},
        "join_relationship_allowlist": [
            {"left_table": "a", "left_column": "id", "right_table": "b", "right_column": "id"}
        ],
    }
    _, hard_passed, _ = asyncio.run(
        service._review_sql_draft(
            QueryPlan(plan_status="ready"),
            SQLDraft(sql="select a.id from mart.a a join mart.b b on b.id = a.id limit 10"),
            context,
        )
    )
    assert hard_passed
    assert critic_calls == [True]
    assert any(event["type"] == "trace.sql_plan" for event in events)
    assert any(event["stage"] == "sql_explain_review" for event in events)


@pytest.mark.skipif(os.getenv("RUN_TRACE_DB_TESTS") != "1", reason="requires local PostgreSQL")
def test_live_postgres_explain_plans_join_without_running_query() -> None:
    result = SQLPlanInspector().inspect(
        "select c.pty_id from mart.ads_cust_info_d c "
        "join mart.dws_cust_aset_d a on a.pty_id = c.pty_id limit 10"
    )
    assert result.status == "ok"
    assert result.node_count >= 2
    assert result.root_total_cost is not None
