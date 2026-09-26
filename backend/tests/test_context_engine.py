from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.agents.llm_sql_actor import LLMSQLActor
from app.context.budget import ContextBudgetExceeded, estimate_context_tokens
from app.context.builder import ContextBuilder, merge_contexts
from app.core.config import Settings
from app.metadata.documents import MetadataDocument
from app.metadata.hybrid_retriever import HybridMetadataRetriever
from app.metadata.retriever import MetadataRetrievalResult
from app.metadata.schema_context import SchemaContextProvider
from app.schemas.query_plan import QueryPlan
from app.schemas.v2_protocol import MissingContextRequest
from app.services.query_service import QueryService


def _raw_context() -> dict:
    asset_columns = [
        {"name": "customer_id", "data_type": "text", "description": "客户关联键"},
        {"name": "amount", "data_type": "numeric", "description": "资产金额"},
    ]
    asset_columns.extend(
        {"name": f"extra_{index}", "data_type": "text", "description": "非必要字段" * 20}
        for index in range(60)
    )
    return {
        "version": "1.0",
        "source": "database",
        "query_intent": "metric_query",
        "scenario": "customer_marketing",
        "retrieval": {
            "strategy": "milvus_bm25_dense_rrf_rerank",
            "keywords": ["客户", "资产"],
            "matched_columns": [{"table_name": "asset", "column_name": "amount"}],
            "evidence": [
                {"doc_id": "metric:total_asset", "bm25_rank": 1},
                {"doc_id": "table:mart.asset", "dense_rank": 1},
            ],
        },
        "tables": [
            {"schema": "mart", "name": "asset", "type": "BASE TABLE",
             "description": "资产事实表", "columns": asset_columns},
            {"schema": "mart", "name": "customer", "type": "BASE TABLE",
             "description": "客户维表", "columns": [
                 {"name": "id", "data_type": "text", "description": "客户键"}
             ]},
        ],
        "metrics": [{"metric_code": "total_asset", "metric_name": "总资产",
                     "formula": "sum(asset.amount)", "description": "总资产口径"}],
        "business_terms": [],
        "join_relationships": [{"id": 1, "left_table": "asset",
                                "left_column": "customer_id", "right_table": "customer",
                                "right_column": "id", "description": "按客户键连接"}],
        "join_relationship_allowlist": [
            {"left_table": "asset", "left_column": "customer_id",
             "right_table": "customer", "right_column": "id"}
        ],
        "question_examples": [{"id": 1, "question": "客户资产示例",
                               "expected_sql": "select 1 " * 500}],
        "rule_constraints": [],
        "table_allowlist": ["asset", "customer"],
        "allowed_columns_by_table": {
            "asset": [column["name"] for column in asset_columns], "customer": ["id"]
        },
        "sensitive_columns": [],
        "semantic_contract": {
            "rules": ["Only read-only SQL"],
            "metric_formulas": {"total_asset": "sum(asset.amount)"},
            "metric_output_aliases": {},
            "reference_date": "2024-12-31",
        },
        "notes": ["Use only retrieved tables and columns."],
        "internal_only": "DO_NOT_SEND_TO_MODEL",
    }


def _plan() -> QueryPlan:
    return QueryPlan.model_validate({
        "question": "客户总资产",
        "data_requirements": {"candidate_tables": ["asset", "customer"]},
        "metrics": [{"name": "总资产", "metric_code": "total_asset"}],
    })


def test_context_budget_retains_grounding_and_keeps_guardrail_catalog_separate() -> None:
    raw = _raw_context()
    bundle = ContextBuilder(1700).build(raw, "客户总资产", _plan())
    prompt = bundle.prompt_context
    assert bundle.token_usage == estimate_context_tokens(prompt) <= 1700
    assert bundle.eviction_count > 0
    assert {row["name"] for row in prompt["tables"]} == {"asset", "customer"}
    asset = next(row for row in prompt["tables"] if row["name"] == "asset")
    assert {"amount", "customer_id"} <= {row["name"] for row in asset["columns"]}
    assert prompt["metrics"][0]["formula"] == "sum(asset.amount)"
    assert prompt["join_relationships"][0]["left_column"] == "customer_id"
    assert "join_relationship_allowlist" not in prompt
    assert len(raw["allowed_columns_by_table"]["asset"]) == 62
    context = {**raw, "prompt_context": prompt}
    messages = LLMSQLActor(None)._build_messages("客户总资产", _plan(), context, None, None)
    assert "DO_NOT_SEND_TO_MODEL" not in messages[-1].content
    assert "sum(asset.amount)" in messages[-1].content


def test_required_evidence_fails_closed_when_budget_is_too_small() -> None:
    raw = _raw_context()
    raw["metrics"][0]["formula"] = " + ".join(["asset.amount"] * 300)
    with pytest.raises(ContextBudgetExceeded):
        ContextBuilder(512).build(raw, "客户总资产", _plan())


def test_schema_qualified_metric_formula_protects_its_column() -> None:
    raw = _raw_context()
    raw["metrics"][0]["formula"] = "sum(mart.asset.amount)"
    bundle = ContextBuilder(1700).build(raw, "客户总资产", _plan())
    asset = next(row for row in bundle.tables if row["name"] == "asset")
    assert "amount" in {row["name"] for row in asset["columns"]}


def test_compaction_omits_sql_instead_of_sending_a_broken_prefix() -> None:
    raw = _raw_context()
    raw["tables"][0]["columns"] = raw["tables"][0]["columns"][:2]
    bundle = ContextBuilder(1400).build(raw, "客户总资产", _plan())
    assert bundle.compaction_count == 1
    assert bundle.examples[0]["example_sql_omitted"] is True
    assert "expected_sql" not in bundle.examples[0]


def test_query_analysis_changes_context_priority_without_fixed_type_quotas() -> None:
    raw = _raw_context()
    raw["retrieval"]["query_analysis"] = {"intent_hint": "join_lookup", "domains": []}
    join_items, _ = ContextBuilder._candidates(raw, "客户总资产", _plan(), set())
    raw["retrieval"]["query_analysis"] = {"intent_hint": "aggregation", "domains": []}
    aggregate_items, _ = ContextBuilder._candidates(raw, "客户总资产", _plan(), set())
    join_priority = {item.doc_id: item.priority for item in join_items}
    aggregate_priority = {item.doc_id: item.priority for item in aggregate_items}
    assert join_priority["join:1"] > aggregate_priority["join:1"]
    assert aggregate_priority["metric:total_asset"] > join_priority["metric:total_asset"]


def test_context_merge_deduplicates_then_evicts_for_targeted_metric() -> None:
    base = _raw_context()
    addition = _raw_context()
    addition["tables"] = [
        {"schema": "mart", "name": "asset", "columns": [
            {"name": "cash", "data_type": "numeric", "description": "现金"}
        ]}
    ]
    addition["metrics"] = [{"metric_code": "cash_asset", "metric_name": "现金资产",
                            "formula": "sum(asset.cash)"}]
    addition["retrieval"]["evidence"] = [{"doc_id": "metric:cash_asset"}]
    merged, duplicates = merge_contexts(base, addition)
    assert duplicates >= 1
    assert len(merged["tables"]) == 2
    assert sum(column["name"] == "cash" for column in merged["tables"][0]["columns"]) == 1
    bundle = ContextBuilder(1900).build(
        merged, "客户总资产", _plan(), pinned_ids={"metric:cash_asset"},
        expansion_count=1, dedup_count=duplicates,
    )
    assert "metric:cash_asset" in bundle.item_ids
    assert bundle.stats()["context_expansion_count"] == 1
    assert bundle.stats()["dedup_count"] >= 1
    assert bundle.token_usage <= 1900


def test_context_expansion_replaces_full_join_policy_snapshot() -> None:
    base = _raw_context()
    addition = _raw_context()
    addition["join_relationship_allowlist"] = []

    merged, _ = merge_contexts(base, addition)

    assert merged["join_relationship_allowlist"] == []
    assert len(merged["join_relationships"]) == 1
    assert base["join_relationship_allowlist"]


def test_provider_expansion_is_callable_and_budgeted(monkeypatch) -> None:
    settings = Settings(
        _env_file=None, retriever_mode="legacy", schema_context_budget=1900,
        stage_retrieval_budget=2, global_retrieval_budget=3,
    )
    engine = SimpleNamespace(connect=lambda: nullcontext(Mock()))
    provider = SchemaContextProvider(engine=engine, settings=settings)
    current = _raw_context()
    initial = ContextBuilder(1900).build(current, "客户总资产", _plan())
    current["prompt_context"] = initial.prompt_context
    current["context_stats"] = initial.stats()
    new_metric = {"metric_code": "cash_asset", "metric_name": "现金资产",
                  "formula": "sum(asset.amount)"}
    addition = _raw_context()
    addition["metrics"] = [new_metric]
    addition["retrieval"]["evidence"] = [{"doc_id": "metric:cash_asset"}]
    monkeypatch.setattr(provider, "_load_from_database", lambda *args, **kwargs: addition)
    lookup = Mock(return_value=MetadataRetrievalResult(
        keywords=["现金"], table_names=["asset"], metric_codes=["cash_asset"],
        business_terms=[], evidence=[{"doc_id": "metric:cash_asset"}],
    ))
    monkeypatch.setattr(provider, "_targeted_retrieval", lookup)
    request = MissingContextRequest(type="metric", concept="现金资产", reason="SQL 缺少指标")
    first = provider.expand(current, request, question="客户总资产", query_plan=_plan())
    assert first["context_expansion_status"] == "expanded"
    assert first["context_stats"]["context_expansion_count"] == 1
    assert any(item["metric_code"] == "cash_asset" for item in first["prompt_context"]["metrics"])
    second = provider.expand(first, request, question="客户总资产", query_plan=_plan())
    assert second["context_stats"]["context_expansion_count"] == 2
    third = provider.expand(second, request, question="客户总资产", query_plan=_plan())
    assert third["context_expansion_status"] == "budget_exhausted"
    assert lookup.call_count == 2


def test_query_service_counts_retrievals_across_plan_refinement() -> None:
    service = object.__new__(QueryService)
    service.schema_context_provider = SimpleNamespace(
        load=lambda **kwargs: {"source": "database", "context_stats": {"retrieval_calls": 1}}
    )
    first = service._load_metadata_context("客户总资产")
    second = service._load_metadata_context("客户总资产", _plan(), previous_context=first)
    assert first["context_stats"]["retrieval_calls"] == 1
    assert second["context_stats"]["retrieval_calls"] == 2


def test_hybrid_targeted_join_uses_strict_milvus_type_filter(monkeypatch) -> None:
    docs = [
        MetadataDocument(f"table:mart.{name}", "table", "", "", name, name,
                         metadata={"schema_name": "mart", "table_name": name})
        for name in ("customer", "transaction", "unrelated")
    ]
    docs.extend([
        MetadataDocument("join:1", "join", "", "", "customer transaction", "", metadata={
            "left_schema": "mart", "left_table": "customer", "left_column": "id",
            "right_schema": "mart", "right_table": "transaction", "right_column": "customer_id",
        }),
        MetadataDocument("join:2", "join", "", "", "transaction unrelated", "", metadata={
            "left_schema": "mart", "left_table": "transaction", "left_column": "id",
            "right_schema": "mart", "right_table": "unrelated", "right_column": "id",
        }),
    ])
    monkeypatch.setattr("app.metadata.hybrid_retriever.load_metadata_documents", lambda _: docs)
    calls = []

    def search(*args):
        calls.append(args)
        return ["join:1", "join:2"]

    store = SimpleNamespace(sync=lambda _: {"total": 5, "upserted": 0, "deleted": 0},
                            search_bm25=search, search_dense=search)
    settings = Settings(_env_file=None, enable_reranker=False, final_top_k=3)
    retriever = HybridMetadataRetriever(Mock(), settings, store=store)
    request = MissingContextRequest(
        type="join_path", concept="客户交易关联", from_table="customer",
        to_table="transaction", reason="缺少关联路径",
    )
    result = retriever.retrieve_targeted(request)
    assert len(result.matched_join_relationships) == 1
    assert set(result.table_names) == {"customer", "transaction"}
    assert all(call[2:] == ('doc_type == "join"', False) for call in calls)
