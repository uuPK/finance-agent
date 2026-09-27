import asyncio
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db.session import engine
from app.evaluation.phase9_metrics import score_case_metrics, summarize_case_metrics
from app.schemas.query import EvaluationExecutionArtifact, QueryResponse
from app.schemas.query_plan import QueryPlan
from app.services.evaluation_service import EvaluationManager, EvaluationRepository


def _case() -> dict:
    return {
        "expected_status": "completed",
        "expected_sql": (
            "select c.pty_id, p.prdt_name from mart.ads_cust_info_d c "
            "join mart.dwd_cust_hold_d h on h.pty_id = c.pty_id "
            "join mart.dim_product p on p.prdt_id = h.prdt_id limit 10"
        ),
        "expected_query_plan": {
            "intent": "detail_lookup",
            "metrics": [{"metric_code": "holding_quantity"}],
            "time_range": {"start": "2024-01-01"},
            "grain": {"level": "customer"},
        },
    }


def _response() -> QueryResponse:
    response = QueryResponse(
        status="completed",
        answer="done",
        retry_count=1,
        elapsed_ms=120,
        query_plan=QueryPlan.model_validate(
            {
                "intent": "detail_lookup",
                "metrics": [{"name": "持仓数量", "metric_code": "holding_quantity"}],
                "time_range": {"start": "2024-01-01"},
                "grain": {"level": "customer"},
            }
        ),
    )
    response._evaluation_retrieval = {
        "strategy": "hybrid",
        "table_names": ["ads_cust_info_d", "dwd_cust_hold_d", "dim_product"],
        "metric_codes": ["holding_quantity"],
        "matched_columns": [
            {"table_name": "ads_cust_info_d", "column_name": "pty_id"},
            {"table_name": "dwd_cust_hold_d", "column_name": "pty_id"},
        ],
        "matched_join_relationships": [
            {
                "left_table": "ads_cust_info_d",
                "left_column": "pty_id",
                "right_table": "dwd_cust_hold_d",
                "right_column": "pty_id",
            },
            {
                "left_table": "dwd_cust_hold_d",
                "left_column": "prdt_id",
                "right_table": "dim_product",
                "right_column": "prdt_id",
            },
        ],
    }
    response._evaluation_runtime = {
        "plan_repairs_used": 0,
        "sql_repairs_used": 1,
        "context_refreshes_used": 0,
        "execution_retries_used": 0,
        "llm_calls": 4,
        "prompt_tokens": 100,
        "completion_tokens": 30,
        "context_tokens_estimated": 500,
    }
    return response


def test_labeled_recall_plan_runtime_cost_and_critic_overhead() -> None:
    response = _response()
    metrics = score_case_metrics(
        _case(),
        response,
        retrieval=response._evaluation_retrieval,
        runtime=response._evaluation_runtime,
        elapsed_ms=125,
        result_correct=True,
        events=[
            {
                "type": "trace.llm_call",
                "stage": "sql_llm_review",
                "status": "passed",
                "output": {"total_tokens": 20},
            },
            {
                "type": "stage.completed",
                "stage": "sql_llm_review",
                "status": "failed",
                "duration_ms": 15,
            },
        ],
    )
    assert metrics["retrieval"]["table_recall_at_k"] == 1
    assert metrics["retrieval"]["join_path_recall_at_k"] == 1
    assert metrics["retrieval"]["column_recall_at_k"] < 1
    assert metrics["plan"]["semantic_accuracy"] == 1
    assert metrics["runtime"]["sql_repair_success"] is True
    assert metrics["runtime"]["plan_repair_success"] is None
    assert metrics["cost"]["input_tokens"] == 100
    assert metrics["critic"]["token_overhead"] == 20
    assert metrics["critic"]["latency_overhead_ms"] == 15
    assert metrics["critic"]["false_pass"] is None
    assert metrics["critic"]["repair_success_after_critic"] is True
    assert "_evaluation_retrieval" not in response.model_dump(mode="json")


def test_missing_gold_and_telemetry_are_unavailable_not_zero() -> None:
    metrics = score_case_metrics(
        {"expected_query_plan": {}, "expected_status": "completed"},
        QueryResponse(status="failed", answer="failed"),
        elapsed_ms=10,
    )
    assert metrics["retrieval"]["table_recall_at_k"] is None
    assert metrics["plan"]["semantic_accuracy"] is None
    assert metrics["cost"]["llm_calls"] is None
    assert metrics["critic"]["false_block"] is None
    assert metrics["critic"]["latency_overhead_ms"] is None


def test_clarification_accuracy_counts_unnecessary_clarification() -> None:
    metrics = score_case_metrics(
        {"expected_query_plan": {}, "expected_status": "completed"},
        QueryResponse(status="needs_clarification", answer="请澄清"),
        elapsed_ms=10,
    )
    assert metrics["plan"]["clarification_accuracy"] == 0


def test_metric_gold_accepts_existing_string_code_labels() -> None:
    response = _response()
    metrics = score_case_metrics(
        {"expected_query_plan": {"metrics": ["holding_quantity"]}},
        response,
        retrieval=response._evaluation_retrieval,
        elapsed_ms=10,
        result_correct=True,
    )
    assert metrics["retrieval"]["metric_recall_at_k"] == 1
    assert metrics["plan"]["metric_coverage"] == 1


def test_summary_uses_labeled_denominators_and_nearest_rank_percentiles() -> None:
    summary = summarize_case_metrics(
        [
            {"retrieval": {"table_recall_at_k": 1.0}, "cost": {"latency_ms": 10}},
            {"retrieval": {"table_recall_at_k": None}, "cost": {"latency_ms": 20}},
            {"retrieval": {"table_recall_at_k": 0.0}, "cost": {"latency_ms": 30}},
        ]
    )
    assert summary["retrieval"]["table_recall_at_k"] == 0.5
    assert summary["retrieval_samples"]["table_recall_at_k"] == 2
    assert summary["cost"]["p50_latency_ms"] == 20
    assert summary["cost"]["p95_latency_ms"] == 30


def test_existing_result_scoring_uses_complete_artifact_and_adds_metrics() -> None:
    result = EvaluationManager()._score(
        {**_case(), "expected_result": {"rows": []}, "difficulty": "simple"},
        _response(),
        None,
        125,
    )
    assert "metrics" in result
    assert result["metrics"]["retrieval"]["join_path_recall_at_k"] == 1


def test_evaluation_manager_collects_trace_usage_without_storing_raw_event_output() -> None:
    saved: list[dict] = []

    class Service:
        event_sink = None

        async def run(
            self, _request: object, *, include_evaluation_artifact: bool
        ) -> QueryResponse:
            assert include_evaluation_artifact
            assert self.event_sink is not None
            await self.event_sink(
                {
                    "type": "trace.llm_call",
                    "stage": "sql_llm_review",
                    "status": "passed",
                    "duration_ms": 7,
                    "output": {
                        "total_tokens": 12,
                        "prompt_tokens": 9,
                        "completion_tokens": 3,
                        "secret": "DO_NOT_STORE",
                    },
                }
            )
            response = QueryResponse(status="completed", answer="done", sql="select 1")
            response._evaluation_execution_artifact = EvaluationExecutionArtifact(
                status="success",
                columns=[],
                rows=[],
                row_count=0,
            )
            return response

    repository = SimpleNamespace(
        save_result=lambda _run_id, _case, result: saved.append(result),
        finish_run=lambda _run_id, _status: None,
    )
    service = Service()
    manager = EvaluationManager(repository=repository, service_factory=lambda: service)
    case = {
        "case_id": uuid4(),
        "question": "测试",
        "expected_status": "completed",
        "expected_query_plan": {},
        "expected_result": {"rows": []},
        "difficulty": "simple",
    }
    asyncio.run(manager._execute(uuid4(), [case, {**case, "case_id": uuid4()}]))

    assert len(saved) == 2
    assert [item["metrics"]["critic"]["token_overhead"] for item in saved] == [12, 12]
    assert [item["metrics"]["cost"]["input_tokens"] for item in saved] == [9, 9]
    assert all("DO_NOT_STORE" not in str(item) for item in saved)
    assert service.event_sink is None


def test_repository_serializes_metrics_into_additive_jsonb_column() -> None:
    captured: list[tuple[str, dict]] = []

    class Connection:
        def execute(self, statement: object, params: dict) -> None:
            captured.append((str(statement), params))

    class Transaction:
        def __enter__(self) -> Connection:
            return Connection()

        def __exit__(self, *_args: object) -> None:
            pass

    repository = EvaluationRepository(engine=SimpleNamespace(begin=Transaction))
    case = {**_case(), "case_id": uuid4(), "expected_result": {"rows": []}, "difficulty": "simple"}
    result = EvaluationManager()._score(case, _response(), None, 125)
    repository.save_result(uuid4(), case, result)

    statement, params = captured[0]
    assert "cast(:metrics as jsonb)" in statement
    assert json.loads(params["metrics"])["retrieval"]["join_path_recall_at_k"] == 1


@pytest.mark.skipif(os.getenv("RUN_TRACE_DB_TESTS") != "1", reason="requires local PostgreSQL")
def test_phase9_migration_column_exists_without_writing_eval_results() -> None:
    with engine.connect() as connection:
        connection.execute(text("select metrics from evaluation.eval_results limit 1"))
