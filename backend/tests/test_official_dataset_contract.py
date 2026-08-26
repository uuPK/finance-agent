import asyncio
from decimal import Decimal
from pathlib import Path

import pytest

from app.agents.llm_query_plan_actor import QueryPlanBuildResult
from app.agents.llm_result_critic import LLMResultCriticResult
from app.agents.llm_sql_actor import LLMSQLActor
from app.agents.query_plan_actor import RuleBasedQueryPlanActor
from app.data.dataset_adapter import DatasetAdapter, DatasetManifest
from app.guardrails.result_validator import ResultHardValidator, ResultValidationResult
from app.guardrails.sql_guardrail import SQLGuardrail
from app.schemas.query_plan import QueryGrain, QueryOutput, QueryPlan
from app.schemas.review import ReviewDecision
from app.services.evaluation_service import _same_result_rows
from app.services.query_service import QueryService
from app.services.sql_executor import SQLExecutionResult

OFFICIAL_COLUMNS = {
    "ads_cust_info_d": {"data_dt", "pty_id", "cust_age", "gender_cd", "edu_cd", "org_id", "name"},
    "dws_cust_aset_d": {"data_dt", "pty_id", "nm_tot_aset", "fc_pur_aset"},
    "dwd_cust_tran_d": {"data_dt", "pty_id", "prdt_id", "buy_amt", "sell_amt"},
    "dim_product": {"prdt_id", "prdt_type_name"},
}


def test_official_sql_is_accepted() -> None:
    findings = SQLGuardrail(
        allowed_tables=set(OFFICIAL_COLUMNS),
        allowed_columns_by_table=OFFICIAL_COLUMNS,
        sensitive_columns={"name"},
    ).validate(
        "SELECT p.prdt_type_name, SUM(t.buy_amt + t.sell_amt) AS trade_amount "
        "FROM mart.dwd_cust_tran_d t JOIN mart.dim_product p ON p.prdt_id = t.prdt_id "
        "WHERE t.data_dt BETWEEN '20260101' AND '20260331' "
        "GROUP BY p.prdt_type_name LIMIT 100"
    )
    assert all(finding.passed for finding in findings)


def test_guardrail_rejects_non_official_schema_function_and_sensitive_column() -> None:
    guardrail = SQLGuardrail(
        allowed_tables={"ads_cust_info_d"},
        allowed_columns_by_table={"ads_cust_info_d": OFFICIAL_COLUMNS["ads_cust_info_d"]},
        sensitive_columns={"name"},
    )
    function = guardrail.validate(
        "SELECT pg_read_file('/etc/passwd') FROM mart.ads_cust_info_d LIMIT 1"
    )
    schema = guardrail.validate("SELECT pty_id FROM secret.ads_cust_info_d LIMIT 1")
    sensitive = guardrail.validate("SELECT name FROM mart.ads_cust_info_d LIMIT 1")
    assert any(not item.passed and item.name == "function_whitelist" for item in function)
    assert any(not item.passed and item.name == "schema_whitelist" for item in schema)
    assert any(not item.passed and item.name == "sensitive_columns" for item in sensitive)


def test_rule_plan_uses_official_asset_and_trade_tables() -> None:
    plan = RuleBasedQueryPlanActor().build("统计总资产超过50万且交易金额超过50万的客户数量")
    assert {metric.metric_code for metric in plan.metrics} >= {
        "customer_count",
        "total_asset",
        "trade_amount",
    }
    assert {"ads_cust_info_d", "dws_cust_aset_d", "dwd_cust_tran_d"} <= set(
        plan.data_requirements.candidate_tables
    )


def test_rule_plan_understands_official_quarter_and_age_distribution() -> None:
    plan = RuleBasedQueryPlanActor().build(
        "不同客户年龄资产分布，规则为小于30、30至49、50至59、以及60岁及以上"
    )
    assert plan.plan_status == "ready"
    assert {metric.metric_code for metric in plan.metrics} >= {"customer_count", "total_asset"}
    assert any(dimension.dimension_code == "cust_age" for dimension in plan.dimensions)
    assert any(assumption.field == "年龄分组" for assumption in plan.assumptions)


def test_evaluation_treats_count_aliases_as_equivalent() -> None:
    assert _same_result_rows(
        [{"customer_count": 75}],
        [{"count": 75}],
        {"metrics": [{"metric_code": "customer_count"}]},
    )


def test_evaluation_treats_decimal_and_json_number_as_equivalent() -> None:
    assert _same_result_rows(
        [{"total_asset": Decimal("12345.678")}, {"total_asset": Decimal("9.0")}],
        [{"total_asset": 12345.678}, {"total_asset": 9.0}],
        {"metrics": [{"metric_code": "total_asset"}]},
    )


def test_evaluation_treats_official_age_and_asset_aliases_as_equivalent() -> None:
    assert _same_result_rows(
        [{"cust_age_group": "[30,50)", "total_asset": Decimal("123.456")}],
        [{"cust_age_type": "[30,50)", "aset": Decimal("123.46")}],
        {
            "metrics": [{"metric_code": "total_asset"}],
            "dimensions": [{"dimension_code": "age_group"}],
        },
    )


def test_rule_plan_preserves_multiple_official_amount_thresholds() -> None:
    plan = RuleBasedQueryPlanActor().build(
        "26年Q1日均资产大于30万的客户，股票交易量大于10万的，其持有的产品属于哪些产品大类"
    )
    assert {metric.metric_code for metric in plan.metrics} >= {
        "daily_average_asset",
        "trade_amount",
        "holding_market_value",
    }
    thresholds = {
        item.metric_code: item.value.normalized
        for item in plan.filters
        if item.metric_code is not None and item.value is not None
    }
    assert thresholds["daily_average_asset"] == 300000
    assert thresholds["trade_amount"] == 100000
    assert any(item.field_code == "up_prdt_type_id" for item in plan.filters)
    assert any(item.dimension_code == "prdt_type_name" for item in plan.dimensions)


def test_rule_plan_preserves_star_market_trade_and_org_distribution() -> None:
    plan = RuleBasedQueryPlanActor().build(
        "查询26年1月10日到26年2月15日期间，科创板交易量大于25万的客户营业部分布情况"
    )
    assert plan.time_range is not None
    assert (plan.time_range.start, plan.time_range.end) == ("20260110", "20260215")
    assert plan.grain is not None and plan.grain.level == "organization"
    assert {item.metric_code for item in plan.metrics} == {"trade_amount"}
    assert any(
        item.metric_code == "trade_amount" and item.value.normalized == 250000
        for item in plan.filters
    )
    assert any(
        item.field_code == "prdt_type_name" and item.value.normalized == "科创板"
        for item in plan.filters
    )
    assert any(item.dimension_code == "org_name" for item in plan.dimensions)


def test_rule_plan_preserves_official_profit_loss_customer_filters() -> None:
    plan = RuleBasedQueryPlanActor().build(
        "钻石卡男性客户，年龄大于40岁，持有比亚迪市值超过1000元，他在26年Q1的盈亏情况"
    )
    assert {metric.metric_code for metric in plan.metrics} >= {
        "profit_loss",
        "holding_market_value",
    }
    assert {item.field_code for item in plan.filters} >= {
        "cust_lvl_cd",
        "gender_cd",
        "cust_age",
        "prdt_name",
    }
    assert any(
        item.metric_code == "holding_market_value" and item.value.normalized == 1000
        for item in plan.filters
    )


def test_rule_plan_uses_verified_official_snapshot_dates_for_age_distribution() -> None:
    plan = RuleBasedQueryPlanActor().build("不同客户年龄段资产分布情况")
    assumptions = {item.field: item.value for item in plan.assumptions}
    assert assumptions["客户快照日期"] == "20260531"
    assert assumptions["资产快照日期"] == "20260331"


def test_rule_plan_includes_all_official_region_dimensions() -> None:
    plan = RuleBasedQueryPlanActor().build("分公司各营业部的客户省份分析统计")
    assert plan.grain is not None and plan.grain.level == "organization"
    assert {item.dimension_code for item in plan.dimensions} >= {
        "up_org_name",
        "org_name",
        "prov_name",
        "city_name",
    }


@pytest.mark.parametrize(
    ("question", "dimension_code"),
    [
        ("截至最新资产日期，请按省份统计客户数。", "prov_name"),
        ("截至最新资产日期，请按城市统计客户数。", "city_name"),
        ("截至最新资产日期，请按客户状态统计总资产不少于30万元的客户数。", "cust_status"),
        ("截至最新资产日期，请按账户来源统计持仓市值和持仓客户数。", "sys_source"),
    ],
)
def test_rule_plan_preserves_generic_grouping_dimension(
    question: str, dimension_code: str
) -> None:
    plan = RuleBasedQueryPlanActor().build(question)
    assert plan.grain is not None and plan.grain.level == "aggregate"
    assert dimension_code in plan.grain.keys
    assert any(
        dimension.dimension_code == dimension_code and dimension.role == "group_by"
        for dimension in plan.dimensions
    )


def test_rule_plan_preserves_all_explicit_multi_metrics() -> None:
    plan = RuleBasedQueryPlanActor().build(
        "截至最新资产日期，请按性别代码统计客户数、平均总资产和总资产。"
    )
    assert {metric.metric_code for metric in plan.metrics} >= {
        "customer_count",
        "average_total_asset",
        "total_asset",
    }
    assert plan.grain is not None and plan.grain.keys == ["gender_cd"]
    assert set(plan.output.columns) >= {"性别代码", "客户数量", "平均总资产", "总资产"}


def test_rule_plan_does_not_turn_snapshot_date_or_average_into_total_asset_output() -> None:
    average_only = RuleBasedQueryPlanActor().build("按学历汇总各学历的客户数量和平均资产。")
    snapshot_only = RuleBasedQueryPlanActor().build(
        "截至最新资产日期，按城市展示持仓市值和持仓客户数量。"
    )
    assert {metric.metric_code for metric in average_only.metrics} == {
        "customer_count",
        "average_total_asset",
    }
    assert {metric.metric_code for metric in snapshot_only.metrics} == {
        "customer_count",
        "holding_market_value",
    }


def test_rule_safeguard_merges_grouping_and_explicit_output_metrics() -> None:
    question = "截至最新资产日期，请按性别代码统计客户数、平均总资产和总资产。"
    deterministic_plan = RuleBasedQueryPlanActor().build(question)
    total_asset = next(
        metric
        for metric in deterministic_plan.metrics
        if metric.metric_code == "total_asset"
    )
    incomplete_llm_plan = deterministic_plan.model_copy(
        update={
            "grain": QueryGrain(level="customer", keys=["pty_id"]),
            "dimensions": [],
            "metrics": [total_asset],
            "output": QueryOutput(columns=["总资产"]),
        }
    )
    guarded = QueryService._apply_rule_plan_safeguards(
        QueryPlanBuildResult(plan=incomplete_llm_plan, source="llm"),
        deterministic_plan,
    )
    assert guarded.source == "rule_fallback"
    assert guarded.plan.grain is not None and guarded.plan.grain.keys == ["gender_cd"]
    assert any(item.dimension_code == "gender_cd" for item in guarded.plan.dimensions)
    assert {metric.metric_code for metric in guarded.plan.metrics} >= {
        "customer_count",
        "average_total_asset",
        "total_asset",
    }
    assert set(guarded.plan.output.columns) >= {"性别代码", "客户数量", "平均总资产", "总资产"}


def test_rule_safeguard_repairs_an_aggregate_plan_missing_group_key() -> None:
    question = "截至最新资产日期，请按省份统计客户数。"
    deterministic_plan = RuleBasedQueryPlanActor().build(question)
    incomplete_llm_plan = deterministic_plan.model_copy(
        update={
            "grain": QueryGrain(level="aggregate", keys=[]),
            "dimensions": [],
        }
    )
    guarded = QueryService._apply_rule_plan_safeguards(
        QueryPlanBuildResult(plan=incomplete_llm_plan, source="llm"),
        deterministic_plan,
    )
    assert guarded.source == "rule_fallback"
    assert guarded.plan.grain is not None and guarded.plan.grain.keys == ["prov_name"]
    assert any(item.dimension_code == "prov_name" for item in guarded.plan.dimensions)


def test_result_critic_failure_is_advisory_after_hard_result_checks() -> None:
    hard_validation = ResultValidationResult(
        passed=True,
        checks=[
            ReviewDecision(
                passed=True,
                score=100,
                stage="result_review",
                reason="Deterministic checks passed.",
                confidence=1.0,
            )
        ],
    )
    critic_result = LLMResultCriticResult(
        status="reviewed",
        decision=ReviewDecision(
            passed=False,
            score=20,
            stage="result_review",
            error_type="empty_result_unexpected",
            reason="Aggregate value is zero.",
            repair_hint="Regenerate SQL.",
            confidence=0.9,
        ),
    )
    merged = QueryService(enable_llm=False)._merge_result_critic_decision(
        hard_validation, critic_result
    )
    assert merged.passed
    assert merged.checks[-1].passed
    assert "Advisory ResultCritic finding" in merged.checks[-1].reason


def test_sql_actor_reuses_only_exact_official_qa_reference() -> None:
    question = "官方参考问题"
    plan = QueryPlan(question=question, output=QueryOutput(columns=["客户数量"], limit=12))
    context = {
        "question_examples": [
            {
                "question": question,
                "tags": ["official", "qa", "qa-006"],
                "expected_sql": "select count(*) as customer_count from mart.ads_cust_info_d",
            }
        ]
    }
    result = asyncio.run(
        LLMSQLActor(llm_service=None).build(question, plan, metadata_context=context)
    )
    assert result.source == "rule_fallback"
    assert result.draft is not None
    assert result.draft.sql.endswith("LIMIT 12")
    assert result.draft.tables == ["ads_cust_info_d"]


def test_sql_actor_does_not_reuse_derived_regression_reference() -> None:
    question = "派生回归题"
    plan = QueryPlan(question=question)
    context = {
        "question_examples": [
            {
                "question": question,
                "tags": ["official_derived", "regression"],
                "expected_sql": "select 1",
            }
        ]
    }
    result = asyncio.run(
        LLMSQLActor(llm_service=None).build(question, plan, metadata_context=context)
    )
    assert result.source == "failed"
    assert result.draft is None


def test_customer_result_requires_pty_id() -> None:
    plan = QueryPlan(grain=QueryGrain(level="customer", keys=["pty_id"]))
    result = SQLExecutionResult(
        status="success",
        sql="SELECT pty_id, total_asset",
        columns=["pty_id", "total_asset"],
        rows=[{"pty_id": "P001", "total_asset": 1}],
        row_count=1,
        truncated=False,
        elapsed_ms=1,
    )
    assert ResultHardValidator().validate(plan, result).passed


def test_dataset_adapter_accepts_only_official_target_tables() -> None:
    manifest = DatasetManifest(
        dataset_version="official-v1",
        source_type="official",
        tables=[
            {
                "source_file": "customers.csv",
                "target_table": "mart.ads_cust_info_d",
                "columns": {"pty_id": "pty_id", "data_dt": "data_dt"},
            }
        ],
    )
    validation = DatasetAdapter().validate(manifest, Path("."))
    assert validation.errors == ["Missing source file: customers.csv"]
    with pytest.raises(ValueError, match="official competition"):
        DatasetManifest(
            dataset_version="official-v1",
            tables=[
                {
                    "source_file": "customers.csv",
                    "target_table": "mart.not_official",
                    "columns": {"pty_id": "pty_id"},
                }
            ],
        )
