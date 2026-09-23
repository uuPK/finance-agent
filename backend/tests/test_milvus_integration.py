"""Opt-in real Milvus test with synthetic text and local deterministic vectors only."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from pymilvus import MilvusClient

from app.core.config import Settings
from app.db.session import engine
from app.metadata.documents import MetadataDocument
from app.metadata.hybrid_retriever import HybridMetadataRetriever
from app.metadata.milvus_store import MilvusMetadataStore
from app.metadata.schema_context import SchemaContextProvider

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_MILVUS_INTEGRATION") != "1",
    reason="set RUN_MILVUS_INTEGRATION=1 to test a running local Milvus",
)


class LocalEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] if "资产" in text else [0.0, 1.0] for text in texts]


def test_native_bm25_and_dense_share_one_milvus_collection() -> None:
    client = MilvusClient(uri="http://localhost:19530", timeout=20)
    store = MilvusMetadataStore(
        uri="http://localhost:19530",
        collection=f"finance_metadata_test_{uuid4().hex[:10]}",
        dimensions=2,
        embedder=LocalEmbedder(),
        embedding_model="local-test",
        client=client,
    )
    documents = [
        MetadataDocument("test:asset", "metric", "asset", "customer", "总资产", "客户总资产金额"),
        MetadataDocument("test:trade", "metric", "trade", "customer", "交易", "客户交易笔数"),
    ]
    try:
        assert store.sync(documents) == {"total": 2, "upserted": 2, "deleted": 0}
        assert store.sync(documents) == {"total": 2, "upserted": 0, "deleted": 0}
        assert store.search_bm25("资产", 2)[0] == "test:asset"
        assert store.search_dense("资产", 2)[0] == "test:asset"
        assert store.sync(documents[:1]) == {"total": 1, "upserted": 0, "deleted": 1}
    finally:
        if client.has_collection(store.collection):
            client.drop_collection(store.collection)


class LocalReranker:
    def rerank(self, query: str, documents: list[str]) -> list[tuple[int, float]]:
        return sorted(
            enumerate(float("资产" in document) for document in documents),
            key=lambda item: (-item[1], item[0]),
        )


def test_postgres_metadata_to_real_milvus_to_hybrid_context() -> None:
    client = MilvusClient(uri="http://localhost:19530", timeout=20)
    store = MilvusMetadataStore(
        uri="http://localhost:19530",
        collection=f"finance_metadata_corpus_test_{uuid4().hex[:10]}",
        dimensions=2,
        embedder=LocalEmbedder(),
        embedding_model="local-test",
        client=client,
    )
    settings = Settings(
        _env_file=None,
        enable_reranker=True,
        retrieval_bm25_top_k=30,
        retrieval_dense_top_k=10,
        rerank_top_n=30,
        final_top_k=20,
    )
    try:
        with engine.connect() as connection:
            result = HybridMetadataRetriever(
                connection, settings, store, LocalReranker()
            ).retrieve("客户总资产")
        assert result.strategy == "milvus_bm25_dense_rrf_rerank"
        assert result.index_sync and result.index_sync["total"] >= 100
        assert result.table_names
        assert result.evidence
        assert any(item["bm25_rank"] is not None for item in result.evidence)
        assert any(item["dense_rank"] is not None for item in result.evidence)
    finally:
        if client.has_collection(store.collection):
            client.drop_collection(store.collection)


def test_hybrid_failure_preserves_legacy_retrieval() -> None:
    settings = Settings(
        _env_file=None,
        retriever_mode="hybrid",
        milvus_uri="http://127.0.0.1:1",
        zhipu_retrieval_api_key="unused-test-key",
    )
    context = SchemaContextProvider(settings=settings).load(question="统计客户平均总资产")
    retrieval = context["retrieval"]
    assert retrieval["strategy"] == "structured_keyword_retrieval"
    assert retrieval["fallback_reason"].startswith("hybrid unavailable:")
    assert retrieval["table_names"]
