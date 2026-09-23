from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from app.core.config import Settings
from app.metadata.documents import MetadataDocument
from app.metadata.fusion import reciprocal_rank_fusion
from app.metadata.hybrid_retriever import HybridMetadataRetriever
from app.metadata.metadata_filter import candidate_filter
from app.metadata.milvus_store import MilvusMetadataStore
from app.metadata.query_analysis import analyze_query
from app.metadata.retrieval_evaluation import RetrievalGold, score_retrieval
from app.metadata.zhipu_retrieval import ZhipuRetrievalClient


def _doc(doc_id: str, kind: str, title: str, row: dict) -> MetadataDocument:
    return MetadataDocument(doc_id, kind, "asset", "customer", title, title, (), row)


def test_query_analysis_filter_and_rrf() -> None:
    analysis = analyze_query("统计高净值客户的平均总资产和基金交易金额")
    assert "asset" in analysis.domains
    assert "trade" in analysis.domains
    assert "customer" in analysis.entities
    assert analysis.intent_hint == "aggregation"
    assert "average_total_asset" in analysis.keywords
    expression = candidate_filter(analysis)
    assert expression and 'domain in' in expression and 'doc_type != "rule"' in expression
    fused = reciprocal_rank_fusion(["a", "b"], ["b", "c"])
    assert [item.doc_id for item in fused] == ["b", "a", "c"]
    assert fused[0].bm25_rank == 2 and fused[0].dense_rank == 1


def test_zhipu_official_embedding_and_rerank_contract() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            (str(request.url), request.headers["Authorization"], json.loads(request.content))
        )
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 1, "embedding": [0.2, 0.3]},
                        {"index": 0, "embedding": [0.1, 0.4]},
                    ]
                },
            )
        return httpx.Response(
            200,
            json={"results": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.2},
            ]},
        )

    client = ZhipuRetrievalClient(
        "test-key", dimensions=256, http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(ValueError, match="dimension"):
        client.embed(["a", "b"])
    # Valid vectors, including reverse API order, must map back to input indexes.
    client.dimensions = 2
    assert client.embed(["a", "b"]) == [[0.1, 0.4], [0.2, 0.3]]
    assert client.rerank("q", ["a", "b"]) == [(1, 0.9), (0, 0.2)]
    assert all(auth == "Bearer test-key" for _, auth, _ in calls)
    assert calls[1][2] == {"model": "embedding-3", "input": ["a", "b"], "dimensions": 2}
    assert calls[2][2] == {
        "model": "rerank", "query": "q", "documents": ["a", "b"], "top_n": 2
    }


class FakeMilvus:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.search_calls: list[tuple[str, str]] = []

    def query(self, **kwargs):
        return [
            {"doc_id": row["doc_id"], "content_hash": row["content_hash"]}
            for row in self.rows.values()
        ]

    def upsert(self, **kwargs):
        for row in kwargs["data"]:
            self.rows[row["doc_id"]] = row

    def delete(self, **kwargs):
        for doc_id in kwargs["ids"]:
            self.rows.pop(doc_id, None)

    def search(self, **kwargs):
        self.search_calls.append((kwargs["anns_field"], kwargs["filter"]))
        ids = ["table:mart.asset", "metric:asset"]
        if kwargs["filter"]:
            ids = ids[:1]
        return [[{"id": doc_id, "entity": {"doc_id": doc_id}} for doc_id in ids]]


def test_milvus_incremental_sync_and_soft_filter_expansion() -> None:
    client = FakeMilvus()
    embedder = Mock()
    embedder.embed.side_effect = lambda texts: [[0.1, 0.2] for _ in texts]
    store = MilvusMetadataStore(
        "http://localhost:19530", "test", 2, embedder, "embedding-3", client
    )
    store.ensure_collection = Mock()
    docs = [
        _doc("table:mart.asset", "table", "资产表", {"table_name": "asset"}),
        _doc("metric:asset", "metric", "资产指标", {"metric_code": "asset"}),
    ]
    assert store.sync(docs) == {"total": 2, "upserted": 2, "deleted": 0}
    assert store.sync(docs) == {"total": 2, "upserted": 0, "deleted": 0}
    assert embedder.embed.call_count == 1
    assert store.search_bm25("资产", 2, 'domain == "asset"') == [
        "table:mart.asset", "metric:asset"
    ]
    assert client.search_calls == [("sparse", 'domain == "asset"'), ("sparse", "")]
    assert store.search_dense("资产", 2) == ["table:mart.asset", "metric:asset"]
    assert store.sync(docs[:1]) == {"total": 1, "upserted": 0, "deleted": 1}


def test_hybrid_grounding_evidence_and_retrieval_metrics(monkeypatch) -> None:
    docs = [
        _doc("table:mart.customer", "table", "客户表", {"table_name": "customer"}),
        _doc("table:mart.asset", "table", "资产表", {"table_name": "asset"}),
        _doc("metric:total_asset", "metric", "总资产", {
            "metric_code": "total_asset", "source_tables": ["asset"],
            "formula": "sum(asset.amount)",
        }),
        _doc("column:mart.asset.amount", "column", "资产金额", {
            "schema_name": "mart", "table_name": "asset", "column_name": "amount"
        }),
        _doc("join:1", "join", "客户资产连接", {
            "left_schema": "mart", "left_table": "customer", "left_column": "id",
            "right_schema": "mart", "right_table": "asset", "right_column": "id"
        }),
    ]
    monkeypatch.setattr("app.metadata.hybrid_retriever.load_metadata_documents", lambda _: docs)
    store = SimpleNamespace(
        sync=lambda _: {"total": 5, "upserted": 0, "deleted": 0},
        search_bm25=lambda *_: ["metric:total_asset", "table:mart.customer"],
        search_dense=lambda *_: ["metric:total_asset", "table:mart.asset"],
    )
    reranker = SimpleNamespace(
        rerank=lambda _query, candidates: [
            (i, 1 / (i + 1)) for i in range(len(candidates))
        ]
    )
    settings = Settings(
        _env_file=None, enable_reranker=True, retrieval_bm25_top_k=2,
        retrieval_dense_top_k=2, rerank_top_n=3, final_top_k=3,
    )
    result = HybridMetadataRetriever(Mock(), settings, store, reranker).retrieve("客户总资产")
    assert set(result.table_names) == {"customer", "asset"}
    assert result.metric_codes == ["total_asset"]
    assert [row["column_name"] for row in result.matched_columns] == ["amount"]
    assert any(
        item["selected_reason"] == "metric_formula_column" for item in result.evidence
    )
    assert len(result.matched_join_relationships) == 1
    assert result.evidence[0]["bm25_rank"] == 1
    assert result.evidence[0]["dense_rank"] == 1
    assert result.evidence[0]["reranker_score"] == 1.0
    gold = RetrievalGold(
        tables=frozenset({"customer", "asset"}),
        metrics=frozenset({"total_asset"}),
        joins=frozenset({("customer", "id", "asset", "id")}),
    )
    assert score_retrieval(result, gold) == {
        "table_recall": 1.0, "column_recall": None,
        "metric_recall": 1.0, "join_path_recall": 1.0,
    }
