import asyncio

from app.schemas.query import QueryRequest
from app.services.query_service import QueryService


def test_query_service_requires_llm_for_sql_generation_after_ready_plan() -> None:
    response = asyncio.run(
        QueryService(enable_llm=False).run(
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
        QueryService(enable_llm=False).run(QueryRequest(question="找出高净值客户"))
    )

    assert response.status == "needs_clarification"
    assert response.sql is None
    assert response.query_plan is not None
    assert response.query_plan.plan_status == "needs_clarification"
    assert response.query_plan.clarifications
    assert response.query_plan.clarifications[0].field == "高净值客户"
    assert all(check.passed for check in response.guardrail_checks)
