from app.agents.answer_actor import AnswerActor
from app.agents.query_plan_actor import RuleBasedQueryPlanActor
from app.services.sql_executor import SQLExecutionResult


def test_answer_actor_renders_detail_preview_answer() -> None:
    question = "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    plan = RuleBasedQueryPlanActor().build(question)
    execution_result = SQLExecutionResult(
        status="success",
        sql="select ...",
        columns=["customer_no", "total_asset", "trade_count_90d"],
        rows=[
            {"customer_no": "C000001", "total_asset": 800000.0, "trade_count_90d": 5},
            {"customer_no": "C000002", "total_asset": 700000.0, "trade_count_90d": 4},
            {"customer_no": "C000003", "total_asset": 650000.0, "trade_count_90d": 6},
        ],
        row_count=3,
    )

    result = AnswerActor().render(
        question=question,
        query_plan=plan,
        execution_result=execution_result,
        preview_rows=execution_result.rows[:2],
    )

    assert "本次查询返回 3 条记录" in result.answer
    assert "客户级" in result.answer
    assert "当前响应展示前 2 条预览" in result.answer
    assert result.row_count == 3
    assert result.preview_row_count == 2


def test_answer_actor_renders_empty_result() -> None:
    question = "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    plan = RuleBasedQueryPlanActor().build(question)
    execution_result = SQLExecutionResult(
        status="success",
        sql="select ...",
        columns=["customer_no", "total_asset", "trade_count_90d"],
        rows=[],
        row_count=0,
    )

    result = AnswerActor().render(
        question=question,
        query_plan=plan,
        execution_result=execution_result,
        preview_rows=[],
    )

    assert result.answer == "查询已完成，未找到满足条件的数据。"
    assert result.row_count == 0
