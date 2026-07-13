import asyncio

from app.agents.llm_query_plan_actor import QueryPlanBuildResult
from app.agents.llm_sql_actor import SQLBuildResult
from app.schemas.query import QueryRequest
from app.schemas.query_plan import QueryDimension, QueryMetric, QueryOutput, QueryPlan
from app.schemas.review import ReviewDecision
from app.schemas.sql import SQLDraft
from app.services.query_service import QueryService


class StaticSchemaContextProvider:
    def load(self, query_plan=None, question=None) -> dict:
        return {
            "version": "1.0",
            "source": "database",
            "table_count": 1,
            "metric_count": 1,
            "retrieval": {
                "strategy": "structured_keyword_retrieval",
                "keywords": [],
                "table_names": ["customer_info"],
                "metric_codes": ["customer_count"],
                "business_terms": [],
                "confidence": 0.9,
            },
            "tables": [],
            "metrics": [{"metric_code": "customer_count"}],
            "business_terms": [],
            "join_relationships": [],
            "question_examples": [],
            "table_allowlist": ["customer_info"],
            "sensitive_columns": [],
            "allowed_columns_by_table": {"customer_info": ["customer_id", "customer_no"]},
        }


class NoopAuditLogger:
    def start_query_run(self, *args, **kwargs) -> None:
        return None

    def finish_query_run(self, *args, **kwargs) -> None:
        return None


def test_query_service_requires_llm_for_sql_generation_after_ready_plan() -> None:
    response = asyncio.run(
        QueryService(
            enable_llm=False,
            schema_context_provider=StaticSchemaContextProvider(),
            audit_logger=NoopAuditLogger(),
        ).run(
            QueryRequest(
                question=(
                    "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
                )
            )
        )
    )

    assert response.status == "failed"
    assert response.sql is None
    assert response.query_plan is not None
    assert response.query_plan.plan_status == "ready"
    assert response.query_plan.intent == "customer_segmentation"
    assert response.query_plan.grain is not None
    assert response.query_plan.grain.level == "customer"
    assert not response.query_plan.clarifications
    assert any(check.name == "sql_actor_failed" for check in response.guardrail_checks)


def test_query_service_returns_clarification_for_ambiguous_business_term() -> None:
    response = asyncio.run(
        QueryService(
            enable_llm=False,
            schema_context_provider=StaticSchemaContextProvider(),
            audit_logger=NoopAuditLogger(),
        ).run(QueryRequest(question="找出高净值客户"))
    )

    assert response.status == "needs_clarification"
    assert response.sql is None
    assert response.query_plan is not None
    assert response.query_plan.plan_status == "needs_clarification"
    assert response.query_plan.clarifications
    assert response.query_plan.clarifications[0].field == "高净值客户"
    assert all(check.passed for check in response.guardrail_checks)


def test_rule_fallback_plans_count_questions_as_aggregate() -> None:
    response = asyncio.run(
        QueryService(
            enable_llm=False,
            schema_context_provider=StaticSchemaContextProvider(),
            audit_logger=NoopAuditLogger(),
        ).run(
            QueryRequest(question="当前资产大于50万的客户总数是多少")
        )
    )

    assert response.query_plan is not None
    assert response.query_plan.intent == "metric_query"
    assert response.query_plan.grain is not None
    assert response.query_plan.grain.level == "aggregate"
    assert response.query_plan.metrics
    assert response.query_plan.metrics[-1].metric_code == "customer_count"


def test_rule_safeguard_completes_ready_plan_that_lost_its_metrics() -> None:
    incomplete = QueryPlan(
        plan_status="ready",
        intent="customer_segmentation",
        confidence=0.9,
    )
    deterministic = QueryPlan(
        plan_status="ready",
        intent="customer_segmentation",
        confidence=0.82,
        metrics=[
            QueryMetric(
                name="trade count",
                metric_code="trade_count_90d",
                aggregation="count",
                is_resolved=True,
            )
        ],
    )

    result = QueryService._apply_rule_plan_safeguards(
        QueryPlanBuildResult(plan=incomplete, source="llm"), deterministic
    )

    assert result.source == "rule_fallback"
    assert result.plan.metrics[0].metric_code == "trade_count_90d"


def test_product_trade_fallback_uses_product_grain_table_after_column_rejection() -> None:
    plan = QueryPlan(
        plan_status="ready",
        intent="metric_query",
        confidence=0.9,
        dimensions=[QueryDimension(name="product", dimension_code="product_type")],
        metrics=[
            QueryMetric(name="customers", metric_code="customer_count"),
            QueryMetric(name="amount", metric_code="trade_amount_90d"),
        ],
        output=QueryOutput(limit=100),
    )
    fallback = QueryService._product_trade_sql_fallback(
        SQLBuildResult(
            draft=SQLDraft(sql="select 1", tables=[], columns=[]),
            source="llm",
            repair_attempt=1,
        ),
        plan,
        {
            "table_allowlist": ["customer_trade", "product_info"],
            "semantic_contract": {"reference_date": "2026-06-30"},
        },
        [
            ReviewDecision(
                passed=False,
                score=0,
                stage="sql_review",
                error_type="column_whitelist",
                reason="Unknown column",
                confidence=1.0,
            )
        ],
    )

    assert fallback.source == "rule_fallback"
    assert fallback.draft is not None
    assert "mart.customer_trade" in fallback.draft.sql
    assert "customer_trade_90d" not in fallback.draft.sql
    assert "trade_date > '2026-04-01'::date" in fallback.draft.sql


def test_net_outflow_fallback_uses_customer_number_and_positive_outflow() -> None:
    plan = QueryPlan(
        plan_status="ready",
        intent="ranking_query",
        confidence=0.9,
        output=QueryOutput(limit=20),
    )

    fallback = QueryService._net_outflow_sql_fallback(
        SQLBuildResult(
            draft=SQLDraft(sql="select 1", tables=[], columns=[]),
            source="llm",
        ),
        "近90天净流出金额最高的客户，展示前20名",
        plan,
        {"table_allowlist": ["customer_info", "customer_net_flow_90d"]},
    )

    assert fallback.source == "rule_fallback"
    assert fallback.draft is not None
    assert "c.customer_no" in fallback.draft.sql
    assert "ROUND(-f.net_flow_amount_90d, 2) AS outflow_amount" in fallback.draft.sql


def test_verified_sql_fallback_avoids_model_call_for_product_analysis() -> None:
    plan = QueryPlan(
        plan_status="ready",
        intent="metric_query",
        confidence=0.9,
        dimensions=[QueryDimension(name="product", dimension_code="product_type")],
        metrics=[
            QueryMetric(name="customers", metric_code="customer_count"),
            QueryMetric(name="amount", metric_code="trade_amount_90d"),
        ],
        output=QueryOutput(limit=100),
    )

    fallback = QueryService._verified_sql_fallback(
        "按产品类型统计近90天交易客户数和交易金额",
        plan,
        {
            "table_allowlist": ["customer_trade", "product_info"],
            "semantic_contract": {"reference_date": "2026-06-30"},
        },
    )

    assert fallback.source == "rule_fallback"
    assert fallback.draft is not None
    assert "mart.customer_trade" in fallback.draft.sql
