from app.schemas.query import QueryResponse
from app.schemas.query_plan import ClarificationQuestion, QueryPlan
from app.services.evaluation_service import EvaluationManager


def test_completed_case_scores_result_by_unordered_business_rows() -> None:
    manager = EvaluationManager()
    case = {
        "expected_status": "completed",
        "expected_query_plan": {"intent": "metric_query"},
        "expected_result": {
            "rows": [
                {"customer_level": "gold", "customer_count": 8},
                {"customer_level": "private", "customer_count": 2},
            ]
        },
        "difficulty": "simple",
    }
    response = QueryResponse(
        status="completed",
        answer="ok",
        sql="select customer_level, customer_count from benchmark limit 10",
        query_plan=QueryPlan(plan_status="ready", intent="metric_query", confidence=0.9),
        result_preview=[
            {"customer_level": "private", "customer_count": 2},
            {"customer_level": "gold", "customer_count": 8},
        ],
    )

    scored = manager._score(case, response, None, 12)

    assert scored["passed"] is True
    assert scored["result_score"] == 100.0
    assert scored["review_status"] == "not_required"


def test_clarification_case_requires_the_expected_terminal_state() -> None:
    manager = EvaluationManager()
    case = {
        "expected_status": "needs_clarification",
        "expected_query_plan": {"clarification_fields": ["高净值客户"]},
        "expected_result": {"clarification_fields": ["高净值客户"]},
        "difficulty": "simple",
    }
    response = QueryResponse(
        status="needs_clarification",
        answer="需要明确口径",
        query_plan=QueryPlan(
            plan_status="needs_clarification",
            clarifications=[
                ClarificationQuestion(
                    field="高净值客户",
                    question="请确认资产门槛",
                    reason="业务口径存在多个定义",
                )
            ],
        ),
    )

    scored = manager._score(case, response, None, 7)

    assert scored["passed"] is True
    assert scored["result_correct"] is True
    assert scored["review_status"] == "not_required"


def test_mismatched_result_is_sent_to_human_review_queue() -> None:
    manager = EvaluationManager()
    case = {
        "expected_status": "completed",
        "expected_query_plan": {},
        "expected_result": {"rows": [{"customer_count": 10}]},
        "difficulty": "medium",
    }
    response = QueryResponse(
        status="completed",
        answer="ok",
        sql="select 9 as customer_count",
        query_plan=QueryPlan(plan_status="ready", confidence=0.95),
        result_preview=[{"customer_count": 9}],
    )

    scored = manager._score(case, response, None, 5)

    assert scored["passed"] is False
    assert scored["review_status"] == "pending"
    assert scored["review_priority"] == "high"
    assert "result_mismatch" in scored["risk_reasons"]
