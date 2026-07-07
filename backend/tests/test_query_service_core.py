import asyncio

from app.schemas.query import QueryRequest
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
