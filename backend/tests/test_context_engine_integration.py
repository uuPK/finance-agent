"""Opt-in end-to-end Context Engine check using local metadata and Zhipu."""

from __future__ import annotations

import os

import pytest

from app.core.config import get_settings
from app.metadata.schema_context import SchemaContextProvider
from app.schemas.v2_protocol import MissingContextRequest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_ZHIPU_RETRIEVAL_INTEGRATION") != "1",
    reason="requires explicit opt-in, local Milvus/PostgreSQL, and authorized Zhipu metadata use",
)


def test_hybrid_context_budget_and_targeted_join_expansion() -> None:
    settings = get_settings()
    assert settings.retriever_mode == "hybrid"
    assert settings.zhipu_retrieval_api_key or settings.zhipu_api_key
    provider = SchemaContextProvider(settings=settings)
    context = provider.load(question="统计客户总资产")
    assert context["source"] == "database"
    assert context["retrieval"]["strategy"] == "milvus_bm25_dense_rrf_rerank"
    assert context["context_stats"]["context_tokens"] <= settings.schema_context_budget

    request = MissingContextRequest(
        type="join_path",
        concept="客户与资产关联",
        from_table="ads_cust_info_d",
        to_table="dws_cust_aset_d",
        reason="SQL 需要真实关联路径",
    )
    expanded = provider.expand(context, request, question="统计客户总资产")
    assert expanded["context_expansion_status"] == "expanded"
    assert expanded["context_stats"]["context_expansion_count"] == 1
    assert expanded["context_stats"]["context_tokens"] <= settings.schema_context_budget
    assert any(
        {row["left_table"], row["right_table"]}
        == {"ads_cust_info_d", "dws_cust_aset_d"}
        for row in expanded["prompt_context"]["join_relationships"]
    )
