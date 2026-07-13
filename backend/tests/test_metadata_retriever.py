from __future__ import annotations

from typing import Any

from app.metadata.retriever import MetadataRetriever
from app.metadata.schema_context import SchemaContextProvider
from app.schemas.query_plan import QueryDimension, QueryMetric, QueryPlan


class FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def mappings(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConnection:
    def execute(self, statement: object) -> FakeResult:
        sql = str(statement)
        if "from metadata.table_metadata" in sql:
            return FakeResult(
                [
                    {
                        "schema_name": "mart",
                        "table_name": "customer_info",
                        "display_name": "客户信息表",
                        "domain": "customer",
                        "description": "客户基础画像与分群字段",
                        "grain": "customer",
                    },
                    {
                        "schema_name": "mart",
                        "table_name": "customer_current_asset",
                        "display_name": "当前客户资产视图",
                        "domain": "asset",
                        "description": "每个客户最新统计日资产",
                        "grain": "customer",
                    },
                    {
                        "schema_name": "mart",
                        "table_name": "customer_trade_90d",
                        "display_name": "近90天客户交易视图",
                        "domain": "trade",
                        "description": "按客户汇总近90天交易次数和金额",
                        "grain": "customer",
                    },
                ]
            )
        if "from metadata.column_metadata" in sql:
            return FakeResult(
                [
                    {
                        "schema_name": "mart",
                        "table_name": "customer_current_asset",
                        "column_name": "total_asset",
                        "display_name": "当前总资产",
                        "description": "最新统计日总资产",
                        "semantic_type": "amount",
                        "is_dimension": False,
                        "is_metric_source": True,
                        "is_sensitive": False,
                    },
                    {
                        "schema_name": "mart",
                        "table_name": "customer_trade_90d",
                        "column_name": "trade_count_90d",
                        "display_name": "近90天交易次数",
                        "description": "近90天交易次数",
                        "semantic_type": "count",
                        "is_dimension": False,
                        "is_metric_source": True,
                        "is_sensitive": False,
                    },
                ]
            )
        if "from metadata.metric_metadata" in sql:
            return FakeResult(
                [
                    {
                        "metric_code": "current_total_asset",
                        "metric_name": "当前总资产",
                        "description": "客户最新统计日总资产。",
                        "formula": "sum(mart.customer_current_asset.total_asset)",
                        "default_aggregation": "sum",
                        "grain": "customer",
                        "source_tables": ["customer_current_asset"],
                        "required_filters": [{"field": "as_of_date", "rule": "latest_snapshot"}],
                    },
                    {
                        "metric_code": "trade_count_90d",
                        "metric_name": "近90天交易次数",
                        "description": "客户近90天交易流水数量。",
                        "formula": "coalesce(mart.customer_trade_90d.trade_count_90d, 0)",
                        "default_aggregation": "sum",
                        "grain": "customer",
                        "source_tables": ["customer_trade_90d"],
                        "required_filters": [{"field": "trade_date", "rule": "last_90_days"}],
                    },
                ]
            )
        if "from metadata.business_terms" in sql:
            return FakeResult(
                [
                    {
                        "term": "活跃客户",
                        "definition": "近90天交易次数大于等于 3 的客户。",
                        "synonyms": ["交易活跃客户"],
                        "default_plan_fragment": {
                            "metric_code": "trade_count_90d",
                            "operator": ">=",
                            "value": 3,
                        },
                        "clarification_required": False,
                    }
                ]
            )
        if "from metadata.join_relationships" in sql:
            return FakeResult(
                [
                    {
                        "left_schema": "mart",
                        "left_table": "customer_info",
                        "left_column": "customer_id",
                        "right_schema": "mart",
                        "right_table": "customer_current_asset",
                        "right_column": "customer_id",
                        "relationship_type": "one_to_one",
                        "description": (
                            "customer_info.customer_id -> "
                            "customer_current_asset.customer_id"
                        ),
                    },
                    {
                        "left_schema": "mart",
                        "left_table": "customer_info",
                        "left_column": "customer_id",
                        "right_schema": "mart",
                        "right_table": "customer_trade_90d",
                        "right_column": "customer_id",
                        "relationship_type": "one_to_one",
                        "description": (
                            "customer_info.customer_id -> "
                            "customer_trade_90d.customer_id"
                        ),
                    },
                ]
            )
        if "from metadata.question_examples" in sql:
            return FakeResult(
                [
                    {
                        "question": "筛选当前资产超过50万且近90天交易次数大于3次的客户",
                        "difficulty": "medium",
                        "expected_sql": "select ... from mart.customer_current_asset ...",
                        "tags": ["高净值客户", "活跃客户"],
                    }
                ]
            )
        return FakeResult([])


def test_metadata_retriever_matches_asset_and_trade_question() -> None:
    result = MetadataRetriever(FakeConnection()).retrieve(
        question="查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    )

    assert "customer_info" in result.table_names
    assert "customer_current_asset" in result.table_names
    assert "customer_trade_90d" in result.table_names
    assert "current_total_asset" in result.metric_codes
    assert "trade_count_90d" in result.metric_codes
    assert result.matched_join_relationships
    assert result.confidence >= 0.8

    context = result.to_context()
    assert context["strategy"] == "structured_keyword_retrieval"
    assert context["keywords"]


def test_semantic_contract_marks_preaggregated_and_product_grain_tables() -> None:
    contract = SchemaContextProvider._semantic_contract(
        {"customer_trade_90d", "customer_trade", "customer_net_flow_90d"},
        [{"metric_code": "trade_count_90d", "formula": "sum(trade_count_90d)"}],
        {"customer_name_masked"},
        "2026-06-30",
    )

    assert any("already aggregated" in rule for rule in contract["rules"])
    assert any("product-level" in rule for rule in contract["rules"])
    assert contract["sensitive_columns_never_select"] == ["customer_name_masked"]
    assert contract["reference_date"] == "2026-06-30"


def test_schema_context_adds_verified_tables_for_product_and_net_outflow_semantics() -> None:
    product_plan = QueryPlan(
        plan_status="ready",
        dimensions=[QueryDimension(name="product", dimension_code="product_type")],
        metrics=[QueryMetric(name="amount", metric_code="trade_amount_90d")],
    )
    net_outflow_plan = QueryPlan(plan_status="ready")

    assert SchemaContextProvider._required_semantic_tables(None, product_plan) == {
        "customer_trade",
        "product_info",
    }
    net_outflow_tables = SchemaContextProvider._required_semantic_tables(
        "近90天净流出客户", net_outflow_plan
    )
    assert net_outflow_tables == {
        "customer_info",
        "customer_net_flow_90d",
    }
