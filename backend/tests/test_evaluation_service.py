from app.schemas.query import QueryResponse
from app.schemas.query_plan import ClarificationQuestion, QueryDimension, QueryMetric, QueryPlan
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


def test_completed_case_matches_metric_code_when_presentation_alias_differs() -> None:
    manager = EvaluationManager()
    case = {
        "expected_status": "completed",
        "expected_query_plan": {"metrics": ["customer_count"]},
        "expected_result": {"rows": [{"customer_count": 500}]},
        "difficulty": "simple",
    }
    response = QueryResponse(
        status="completed",
        answer="ok",
        sql="select count(*) as display_count from benchmark limit 1",
        query_plan=QueryPlan(
            plan_status="ready",
            confidence=0.9,
            metrics=[
                QueryMetric(
                    name="display_count",
                    alias="display_count",
                    metric_code="customer_count",
                )
            ],
        ),
        result_preview=[{"display_count": 500}],
    )

    scored = manager._score(case, response, None, 12)

    assert scored["passed"] is True
    assert scored["result_correct"] is True


def test_completed_case_maps_known_metric_source_aliases() -> None:
    manager = EvaluationManager()
    case = {
        "expected_status": "completed",
        "expected_query_plan": {},
        "expected_result": {"rows": [{"current_total_asset": 500000}]},
        "difficulty": "simple",
    }
    response = QueryResponse(
        status="completed",
        answer="ok",
        sql="select total_asset from benchmark limit 1",
        query_plan=QueryPlan(
            plan_status="ready",
            confidence=0.9,
            metrics=[QueryMetric(name="asset", metric_code="current_total_asset")],
        ),
        result_preview=[{"total_asset": 500000}],
    )

    scored = manager._score(case, response, None, 12)

    assert scored["passed"] is True


def test_completed_case_maps_known_presentation_aliases() -> None:
    manager = EvaluationManager()
    case = {
        "expected_status": "completed",
        "expected_query_plan": {},
        "expected_result": {"rows": [{"customer_count": 8, "trade_amount_90d": 125.5}]},
        "difficulty": "simple",
    }
    response = QueryResponse(
        status="completed",
        answer="ok",
        sql="select 8 as customer_count, 125.5 as trade_amount limit 1",
        query_plan=QueryPlan(plan_status="ready", confidence=0.9),
        result_preview=[{"交易客户数": 8, "交易金额": 125.5}],
    )

    scored = manager._score(case, response, None, 12)

    assert scored["passed"] is True


def test_completed_case_keeps_stable_presentation_alias_over_incorrect_plan_dimension() -> None:
    manager = EvaluationManager()
    case = {
        "expected_status": "completed",
        "expected_query_plan": {},
        "expected_result": {
            "rows": [
                {
                    "campaign_code": "CAM0001",
                    "response_customer_count": 0,
                    "response_rate": 0.0,
                }
            ]
        },
        "difficulty": "simple",
    }
    response = QueryResponse(
        status="completed",
        answer="ok",
        sql="select 'CAM0001' as campaign_code limit 1",
        query_plan=QueryPlan(
            plan_status="ready",
            confidence=0.9,
            dimensions=[QueryDimension(name="营销活动", dimension_code="campaign_id")],
        ),
        result_preview=[{"营销活动": "CAM0001", "已响应客户数": 0, "响应率": 0.0}],
    )

    scored = manager._score(case, response, None, 12)

    assert scored["passed"] is True


def test_completed_case_allows_extra_display_fields_but_requires_expected_fields() -> None:
    manager = EvaluationManager()
    case = {
        "expected_status": "completed",
        "expected_query_plan": {},
        "expected_result": {"rows": [{"customer_no": "C001", "customer_count": 8}]},
        "difficulty": "simple",
    }
    response = QueryResponse(
        status="completed",
        answer="ok",
        sql="select customer_no, customer_count, customer_level from benchmark limit 1",
        query_plan=QueryPlan(plan_status="ready", confidence=0.9),
        result_preview=[{"customer_no": "C001", "customer_count": 8, "customer_level": "gold"}],
    )

    scored = manager._score(case, response, None, 12)

    assert scored["passed"] is True


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
