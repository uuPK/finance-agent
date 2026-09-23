"""Opt-in, retrieval-only comparison against the preserved legacy retriever."""

from __future__ import annotations

import os

import pytest

from app.core.config import get_settings
from app.db.session import engine
from app.metadata.hybrid_retriever import HybridMetadataRetriever
from app.metadata.retrieval_evaluation import RetrievalGold, score_retrieval
from app.metadata.retriever import MetadataRetriever

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_ZHIPU_RETRIEVAL_INTEGRATION") != "1",
    reason="requires explicit opt-in, local Milvus, PostgreSQL, and a Zhipu key",
)


CASES = [
    (
        "统计客户平均总资产",
        RetrievalGold(
            tables=frozenset({"ads_cust_info_d", "dws_cust_aset_d"}),
            columns=frozenset({
                ("dws_cust_aset_d", "nm_tot_aset"),
                ("dws_cust_aset_d", "fc_pur_aset"),
            }),
            metrics=frozenset({"average_total_asset"}),
            joins=frozenset({
                ("ads_cust_info_d", "pty_id", "dws_cust_aset_d", "pty_id")
            }),
        ),
    ),
    (
        "按营业部统计客户数量",
        RetrievalGold(
            tables=frozenset({"ads_cust_info_d", "dim_branch"}),
            columns=frozenset({("ads_cust_info_d", "org_id"), ("dim_branch", "org_id")}),
            metrics=frozenset({"customer_count"}),
            joins=frozenset({
                ("ads_cust_info_d", "org_id", "dim_branch", "org_id")
            }),
        ),
    ),
    (
        "统计客户交易金额",
        RetrievalGold(
            tables=frozenset({"ads_cust_info_d", "dwd_cust_tran_d"}),
            columns=frozenset({
                ("dwd_cust_tran_d", "buy_amt"),
                ("dwd_cust_tran_d", "sell_amt"),
            }),
            metrics=frozenset({"trade_amount"}),
            joins=frozenset({
                ("ads_cust_info_d", "pty_id", "dwd_cust_tran_d", "pty_id")
            }),
        ),
    ),
    (
        "统计客户持仓市值",
        RetrievalGold(
            tables=frozenset({"ads_cust_info_d", "dwd_cust_hold_d"}),
            columns=frozenset({("dwd_cust_hold_d", "mkt_val")}),
            metrics=frozenset({"holding_market_value"}),
            joins=frozenset({
                ("ads_cust_info_d", "pty_id", "dwd_cust_hold_d", "pty_id")
            }),
        ),
    ),
    (
        "统计客户现金净流入",
        RetrievalGold(
            tables=frozenset({"ads_cust_info_d", "dws_cust_fin_d"}),
            columns=frozenset({
                ("dws_cust_fin_d", "cash_in"),
                ("dws_cust_fin_d", "cash_out"),
            }),
            metrics=frozenset({"net_cash_inflow"}),
            joins=frozenset({
                ("ads_cust_info_d", "pty_id", "dws_cust_fin_d", "pty_id")
            }),
        ),
    ),
]


def test_hybrid_recall_compared_with_legacy() -> None:
    settings = get_settings()
    assert settings.zhipu_retrieval_api_key or settings.zhipu_api_key
    hybrid_totals = dict.fromkeys(
        ("table_recall", "column_recall", "metric_recall", "join_path_recall"), 0.0
    )
    legacy_totals = dict.fromkeys(hybrid_totals, 0.0)
    with engine.connect() as connection:
        for question, gold in CASES:
            hybrid = HybridMetadataRetriever(connection, settings).retrieve(question)
            legacy = MetadataRetriever(connection).retrieve(question)
            assert hybrid.strategy == "milvus_bm25_dense_rrf_rerank"
            for key, score in score_retrieval(hybrid, gold).items():
                hybrid_totals[key] += score or 0.0
            for key, score in score_retrieval(legacy, gold).items():
                legacy_totals[key] += score or 0.0
    assert all(hybrid_totals[key] >= legacy_totals[key] for key in hybrid_totals), (
        hybrid_totals,
        legacy_totals,
    )
