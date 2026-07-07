from app.agents.query_plan_actor import RuleBasedQueryPlanActor
from app.guardrails.result_validator import ResultHardValidator
from app.services.sql_executor import SQLExecutionResult


def test_result_validator_passes_customer_result_with_identifier() -> None:
    plan = RuleBasedQueryPlanActor().build(
        "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    )
    result = SQLExecutionResult(
        status="success",
        sql="select ...",
        columns=["customer_no", "total_asset"],
        rows=[{"customer_no": "C000001", "total_asset": 800000.0}],
        row_count=1,
    )

    validation = ResultHardValidator().validate(plan, result)

    assert validation.passed


def test_result_validator_rejects_wrong_customer_grain() -> None:
    plan = RuleBasedQueryPlanActor().build(
        "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    )
    result = SQLExecutionResult(
        status="success",
        sql="select ...",
        columns=["total_asset"],
        rows=[{"total_asset": 800000.0}],
        row_count=1,
    )

    validation = ResultHardValidator().validate(plan, result)

    assert not validation.passed
    assert validation.error_type == "wrong_grain"


def test_result_validator_rejects_truncated_large_result() -> None:
    plan = RuleBasedQueryPlanActor().build(
        "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    )
    result = SQLExecutionResult(
        status="success",
        sql="select ...",
        columns=["customer_no"],
        rows=[{"customer_no": "C000001"}],
        row_count=1,
        truncated=True,
    )

    validation = ResultHardValidator(max_result_rows=1).validate(plan, result)

    assert not validation.passed
    assert validation.error_type == "result_too_large"
