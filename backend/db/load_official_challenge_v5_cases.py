# ruff: noqa: E501
"""Load a fifth, 40-case held-out challenge set from official tables only.

The test uses a January month-end snapshot and February flow windows that differ
from prior challenge sets. Expected results are regenerated from the official
database and no question is added to retrieval examples.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import engine

DATASET_VERSION = "official-v1-challenge-v5"
SOURCE_TYPE = "official_challenge_v5"
TAG = "official_challenge_v5"


@dataclass(frozen=True)
class ChallengeCase:
    code: str
    question: str
    difficulty: str
    sql: str
    topic: str


def case(no: int, question: str, difficulty: str, sql: str, topic: str) -> ChallengeCase:
    return ChallengeCase(f"V5-{no:03d}", question, difficulty, sql.strip(), topic)


CASES: tuple[ChallengeCase, ...] = (
    case(1, "当前客户快照中，年龄不低于65岁的去重客户有多少位？", "simple", """
        select count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d where cust_age >= 65 limit 1
    """, "customer"),
    case(2, "当前客户快照中，已关联营业部的去重客户有多少位？", "simple", """
        select count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d where org_id is not null and org_id <> '' limit 1
    """, "customer"),
    case(3, "请按客户类型计算当前客户平均年龄，展示前10类。", "medium", """
        select cust_type, avg(cust_age) as average_customer_age
        from mart.ads_cust_info_d
        group by cust_type order by average_customer_age desc nulls last, cust_type limit 10
    """, "customer"),
    case(4, "请按省份和客户等级代码联合统计当前客户数量，展示前20组。", "medium", """
        select prov_name, cust_lvl_cd, count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d
        group by prov_name, cust_lvl_cd
        order by customer_count desc, prov_name, cust_lvl_cd limit 20
    """, "customer"),
    case(5, "请按一级营业部统计当前客户平均年龄，展示平均年龄最高的前10个营业部。", "medium", """
        select b.up_org_name, avg(c.cust_age) as average_customer_age
        from mart.ads_cust_info_d c join mart.dim_branch b on b.org_id = c.org_id
        group by b.up_org_name
        order by average_customer_age desc nulls last, b.up_org_name limit 10
    """, "customer"),
    case(6, "当前客户快照中，女性客户的去重数量是多少？", "simple", """
        select count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d where gender_cd = '5000003' limit 1
    """, "customer"),
    case(7, "截至2026年1月31日，客户现金资产合计是多少？", "simple", """
        select sum(coalesce(nm_bal, 0) + coalesce(fc_bal, 0)) as cash_asset
        from mart.dws_cust_aset_d where data_dt = '20260131' limit 1
    """, "asset"),
    case(8, "截至2026年1月31日，总资产达到20万元的去重客户有多少位？", "simple", """
        select count(distinct pty_id) as customer_count
        from mart.dws_cust_aset_d
        where data_dt = '20260131'
          and coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0) >= 200000
        limit 1
    """, "asset"),
    case(9, "截至2026年1月31日，请按客户类型汇总总资产，展示前10类。", "medium", """
        select c.cust_type, sum(coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0)) as total_asset
        from mart.dws_cust_aset_d a join mart.ads_cust_info_d c on c.pty_id = a.pty_id
        where a.data_dt = '20260131'
        group by c.cust_type order by total_asset desc, c.cust_type limit 10
    """, "asset"),
    case(10, "截至2026年1月31日，请按客户等级代码统计平均总资产，展示前10个等级。", "medium", """
        select c.cust_lvl_cd, avg(coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0)) as average_total_asset
        from mart.dws_cust_aset_d a join mart.ads_cust_info_d c on c.pty_id = a.pty_id
        where a.data_dt = '20260131'
        group by c.cust_lvl_cd order by average_total_asset desc nulls last, c.cust_lvl_cd limit 10
    """, "asset"),
    case(11, "截至2026年1月31日，请按一级营业部统计总资产，展示前10个营业部。", "medium", """
        select b.up_org_name, sum(coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0)) as total_asset
        from mart.dws_cust_aset_d a
        join mart.ads_cust_info_d c on c.pty_id = a.pty_id
        join mart.dim_branch b on b.org_id = c.org_id
        where a.data_dt = '20260131'
        group by b.up_org_name order by total_asset desc, b.up_org_name limit 10
    """, "asset"),
    case(12, "截至2026年1月31日，请按性别代码统计总资产达到30万元的客户数。", "medium", """
        select c.gender_cd, count(distinct a.pty_id) as customer_count
        from mart.dws_cust_aset_d a join mart.ads_cust_info_d c on c.pty_id = a.pty_id
        where a.data_dt = '20260131'
          and coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0) >= 300000
        group by c.gender_cd order by customer_count desc, c.gender_cd limit 10
    """, "asset"),
    case(13, "2026年2月，客户买入金额合计是多少？", "simple", """
        select sum(coalesce(buy_amt, 0)) as buy_amount
        from mart.dwd_cust_tran_d where data_dt between '20260201' and '20260228' limit 1
    """, "trade"),
    case(14, "2026年2月，请按账户来源统计卖出金额，展示前10个来源。", "medium", """
        select sys_source, sum(coalesce(sell_amt, 0)) as sell_amount
        from mart.dwd_cust_tran_d where data_dt between '20260201' and '20260228'
        group by sys_source order by sell_amount desc, sys_source limit 10
    """, "trade"),
    case(15, "2026年2月，请按产品市场统计交易金额，展示前10个市场。", "medium", """
        select p.market_id, sum(coalesce(t.buy_amt, 0) + coalesce(t.sell_amt, 0)) as trade_amount
        from mart.dwd_cust_tran_d t join mart.dim_product p on p.prdt_id = t.prdt_id
        where t.data_dt between '20260201' and '20260228'
        group by p.market_id order by trade_amount desc, p.market_id limit 10
    """, "trade"),
    case(16, "2026年2月，累计买入金额达到5万元的去重客户有多少位？", "medium", """
        select count(*) as customer_count from (
          select pty_id from mart.dwd_cust_tran_d where data_dt between '20260201' and '20260228'
          group by pty_id having sum(coalesce(buy_amt, 0)) >= 50000
        ) buy_customers limit 1
    """, "trade"),
    case(17, "2026年2月，发生交易的客户平均交易金额是多少？", "complex", """
        select avg(trade_amount) as average_trade_amount from (
          select pty_id, sum(coalesce(buy_amt, 0) + coalesce(sell_amt, 0)) as trade_amount
          from mart.dwd_cust_tran_d where data_dt between '20260201' and '20260228'
          group by pty_id
        ) customer_trades limit 1
    """, "trade"),
    case(18, "2026年2月，请按客户状态统计交易客户数和交易金额，展示前10个状态。", "complex", """
        select c.cust_status, count(distinct t.pty_id) as customer_count,
               sum(coalesce(t.buy_amt, 0) + coalesce(t.sell_amt, 0)) as trade_amount
        from mart.dwd_cust_tran_d t join mart.ads_cust_info_d c on c.pty_id = t.pty_id
        where t.data_dt between '20260201' and '20260228'
        group by c.cust_status order by trade_amount desc, c.cust_status limit 10
    """, "trade"),
    case(19, "2026年2月，请按一级产品分类统计交易费用，展示前10个分类。", "medium", """
        select p.up_prdt_type_name, sum(coalesce(t.buy_fare, 0) + coalesce(t.sell_fare, 0)) as trade_fee
        from mart.dwd_cust_tran_d t join mart.dim_product p on p.prdt_id = t.prdt_id
        where t.data_dt between '20260201' and '20260228'
        group by p.up_prdt_type_name order by trade_fee desc, p.up_prdt_type_name limit 10
    """, "trade"),
    case(20, "截至2026年1月31日，客户持仓市值合计是多少？", "simple", """
        select sum(coalesce(mkt_val, 0)) as holding_market_value
        from mart.dwd_cust_hold_d where data_dt = '20260131' limit 1
    """, "holding"),
    case(21, "截至2026年1月31日，请按账户来源统计持仓市值，展示前10个来源。", "medium", """
        select sys_source, sum(coalesce(mkt_val, 0)) as holding_market_value
        from mart.dwd_cust_hold_d where data_dt = '20260131'
        group by sys_source order by holding_market_value desc, sys_source limit 10
    """, "holding"),
    case(22, "截至2026年1月31日，请按币种统计持仓客户数，展示前10种币种。", "medium", """
        select ccy, count(distinct pty_id) as customer_count
        from mart.dwd_cust_hold_d where data_dt = '20260131'
        group by ccy order by customer_count desc, ccy limit 10
    """, "holding"),
    case(23, "截至2026年1月31日，请按产品市场统计持仓市值，展示前10个市场。", "medium", """
        select p.market_id, sum(coalesce(h.mkt_val, 0)) as holding_market_value
        from mart.dwd_cust_hold_d h join mart.dim_product p on p.prdt_id = h.prdt_id
        where h.data_dt = '20260131'
        group by p.market_id order by holding_market_value desc, p.market_id limit 10
    """, "holding"),
    case(24, "截至2026年1月31日，持仓市值达到10万元的去重客户有多少位？", "simple", """
        select count(*) as customer_count from (
          select pty_id from mart.dwd_cust_hold_d where data_dt = '20260131'
          group by pty_id having sum(coalesce(mkt_val, 0)) >= 100000
        ) holding_customers limit 1
    """, "holding"),
    case(25, "截至2026年1月31日，请按客户类型汇总持仓市值，展示前10类。", "medium", """
        select c.cust_type, sum(coalesce(h.mkt_val, 0)) as holding_market_value
        from mart.dwd_cust_hold_d h join mart.ads_cust_info_d c on c.pty_id = h.pty_id
        where h.data_dt = '20260131'
        group by c.cust_type order by holding_market_value desc, c.cust_type limit 10
    """, "holding"),
    case(26, "2026年2月，客户现金流入金额合计是多少？", "simple", """
        select sum(coalesce(cash_in, 0)) as cash_in
        from mart.dws_cust_fin_d where data_dt between '20260201' and '20260228' limit 1
    """, "cash_flow"),
    case(27, "2026年2月，客户转账金额合计是多少？", "simple", """
        select sum(coalesce(tran_in, 0) + coalesce(tran_out, 0)) as transfer_amount
        from mart.dws_cust_fin_d where data_dt between '20260201' and '20260228' limit 1
    """, "cash_flow"),
    case(28, "2026年2月，请按账户来源统计净资金流入，展示前10个来源。", "medium", """
        select sys_source,
               sum(coalesce(cash_in, 0) + coalesce(tran_in, 0) + coalesce(assign_in, 0)
                   - coalesce(cash_out, 0) - coalesce(tran_out, 0) - coalesce(assign_out, 0)) as net_cash_flow
        from mart.dws_cust_fin_d where data_dt between '20260201' and '20260228'
        group by sys_source order by net_cash_flow desc, sys_source limit 10
    """, "cash_flow"),
    case(29, "2026年2月，请按客户类型统计现金流入金额，展示前10类。", "medium", """
        select c.cust_type, sum(coalesce(f.cash_in, 0)) as cash_in
        from mart.dws_cust_fin_d f join mart.ads_cust_info_d c on c.pty_id = f.pty_id
        where f.data_dt between '20260201' and '20260228'
        group by c.cust_type order by cash_in desc, c.cust_type limit 10
    """, "cash_flow"),
    case(30, "2026年2月，累计现金流入达到10万元的去重客户有多少位？", "medium", """
        select count(*) as customer_count from (
          select pty_id from mart.dws_cust_fin_d where data_dt between '20260201' and '20260228'
          group by pty_id having sum(coalesce(cash_in, 0)) >= 100000
        ) cash_in_customers limit 1
    """, "cash_flow"),
    case(31, "截至2026年1月31日总资产达到20万元且2026年2月发生交易的客户有多少位？", "complex", """
        with asset_customers as (
          select pty_id from mart.dws_cust_aset_d
          where data_dt = '20260131' and coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0) >= 200000
        ), trade_customers as (
          select distinct pty_id from mart.dwd_cust_tran_d where data_dt between '20260201' and '20260228'
        )
        select count(*) as customer_count from asset_customers a join trade_customers t on t.pty_id = a.pty_id limit 1
    """, "segment"),
    case(32, "截至2026年1月31日持仓市值达到10万元且2026年2月累计买入金额达到5万元的客户有多少位？", "complex", """
        with holding_customers as (
          select pty_id from mart.dwd_cust_hold_d where data_dt = '20260131'
          group by pty_id having sum(coalesce(mkt_val, 0)) >= 100000
        ), buyers as (
          select pty_id from mart.dwd_cust_tran_d where data_dt between '20260201' and '20260228'
          group by pty_id having sum(coalesce(buy_amt, 0)) >= 50000
        )
        select count(*) as customer_count from holding_customers h join buyers b on b.pty_id = h.pty_id limit 1
    """, "segment"),
    case(33, "截至2026年1月31日现金资产达到5万元且2026年2月净资金流入为正的客户有多少位？", "complex", """
        with cash_customers as (
          select pty_id from mart.dws_cust_aset_d
          where data_dt = '20260131' and coalesce(nm_bal, 0) + coalesce(fc_bal, 0) >= 50000
        ), positive_flow_customers as (
          select pty_id from mart.dws_cust_fin_d where data_dt between '20260201' and '20260228'
          group by pty_id
          having sum(coalesce(cash_in, 0) + coalesce(tran_in, 0) + coalesce(assign_in, 0)
                     - coalesce(cash_out, 0) - coalesce(tran_out, 0) - coalesce(assign_out, 0)) > 0
        )
        select count(*) as customer_count from cash_customers c join positive_flow_customers f on f.pty_id = c.pty_id limit 1
    """, "segment"),
    case(34, "截至2026年1月31日，请按省份统计总资产达到30万元且2026年2月发生交易的客户数，展示前10个省份。", "complex", """
        with asset_customers as (
          select pty_id from mart.dws_cust_aset_d
          where data_dt = '20260131' and coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0) >= 300000
        ), trade_customers as (
          select distinct pty_id from mart.dwd_cust_tran_d where data_dt between '20260201' and '20260228'
        )
        select c.prov_name, count(distinct a.pty_id) as customer_count
        from asset_customers a join trade_customers t on t.pty_id = a.pty_id
        join mart.ads_cust_info_d c on c.pty_id = a.pty_id
        group by c.prov_name order by customer_count desc, c.prov_name limit 10
    """, "segment"),
    case(35, "截至2026年1月31日，请按客户类型统计总资产和持仓市值，展示前10类。", "complex", """
        with asset_by_customer as (
          select pty_id, sum(coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0)) as total_asset
          from mart.dws_cust_aset_d where data_dt = '20260131' group by pty_id
        ), holding_by_customer as (
          select pty_id, sum(coalesce(mkt_val, 0)) as holding_market_value
          from mart.dwd_cust_hold_d where data_dt = '20260131' group by pty_id
        )
        select c.cust_type, sum(a.total_asset) as total_asset,
               sum(coalesce(h.holding_market_value, 0)) as holding_market_value
        from asset_by_customer a join mart.ads_cust_info_d c on c.pty_id = a.pty_id
        left join holding_by_customer h on h.pty_id = a.pty_id
        group by c.cust_type order by total_asset desc, c.cust_type limit 10
    """, "segment"),
    case(36, "2026年2月，请按一级营业部统计交易金额和净资金流入，展示前10个营业部。", "complex", """
        with trade_by_customer as (
          select pty_id, sum(coalesce(buy_amt, 0) + coalesce(sell_amt, 0)) as trade_amount
          from mart.dwd_cust_tran_d where data_dt between '20260201' and '20260228' group by pty_id
        ), flow_by_customer as (
          select pty_id, sum(coalesce(cash_in, 0) + coalesce(tran_in, 0) + coalesce(assign_in, 0)
                              - coalesce(cash_out, 0) - coalesce(tran_out, 0) - coalesce(assign_out, 0)) as net_cash_flow
          from mart.dws_cust_fin_d where data_dt between '20260201' and '20260228' group by pty_id
        )
        select b.up_org_name, sum(t.trade_amount) as trade_amount, sum(coalesce(f.net_cash_flow, 0)) as net_cash_flow
        from trade_by_customer t join mart.ads_cust_info_d c on c.pty_id = t.pty_id
        join mart.dim_branch b on b.org_id = c.org_id left join flow_by_customer f on f.pty_id = t.pty_id
        group by b.up_org_name order by trade_amount desc, b.up_org_name limit 10
    """, "segment"),
    case(37, "2026年2月发生过股票类交易且截至2026年1月31日总资产达到20万元的客户有多少位？", "complex", """
        with asset_customers as (
          select pty_id from mart.dws_cust_aset_d
          where data_dt = '20260131' and coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0) >= 200000
        ), stock_trade_customers as (
          select distinct t.pty_id from mart.dwd_cust_tran_d t join mart.dim_product p on p.prdt_id = t.prdt_id
          where t.data_dt between '20260201' and '20260228' and p.up_prdt_type_id = 'PT040000'
        )
        select count(*) as customer_count from asset_customers a join stock_trade_customers t on t.pty_id = a.pty_id limit 1
    """, "segment"),
    case(38, "截至2026年1月31日持有至少两种产品且2026年2月净资金流入为正的客户有多少位？", "complex", """
        with multi_product_customers as (
          select pty_id from mart.dwd_cust_hold_d where data_dt = '20260131'
          group by pty_id having count(distinct prdt_id) >= 2
        ), positive_flow_customers as (
          select pty_id from mart.dws_cust_fin_d where data_dt between '20260201' and '20260228'
          group by pty_id
          having sum(coalesce(cash_in, 0) + coalesce(tran_in, 0) + coalesce(assign_in, 0)
                     - coalesce(cash_out, 0) - coalesce(tran_out, 0) - coalesce(assign_out, 0)) > 0
        )
        select count(*) as customer_count from multi_product_customers h join positive_flow_customers f on f.pty_id = h.pty_id limit 1
    """, "segment"),
    case(39, "截至2026年1月31日，请按一级产品分类统计持仓客户数和2026年2月交易客户数，展示前10类。", "complex", """
        with holding_by_type as (
          select p.up_prdt_type_name, count(distinct h.pty_id) as holding_customer_count
          from mart.dwd_cust_hold_d h join mart.dim_product p on p.prdt_id = h.prdt_id
          where h.data_dt = '20260131' group by p.up_prdt_type_name
        ), trade_by_type as (
          select p.up_prdt_type_name, count(distinct t.pty_id) as trade_customer_count
          from mart.dwd_cust_tran_d t join mart.dim_product p on p.prdt_id = t.prdt_id
          where t.data_dt between '20260201' and '20260228' group by p.up_prdt_type_name
        )
        select h.up_prdt_type_name, h.holding_customer_count, coalesce(t.trade_customer_count, 0) as trade_customer_count
        from holding_by_type h left join trade_by_type t on t.up_prdt_type_name = h.up_prdt_type_name
        order by h.holding_customer_count desc, h.up_prdt_type_name limit 10
    """, "segment"),
    case(40, "截至2026年1月31日总资产达到20万元、持仓市值达到10万元且2026年2月发生交易的客户有多少位？", "complex", """
        with asset_customers as (
          select pty_id from mart.dws_cust_aset_d
          where data_dt = '20260131' and coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0) >= 200000
        ), holding_customers as (
          select pty_id from mart.dwd_cust_hold_d where data_dt = '20260131'
          group by pty_id having sum(coalesce(mkt_val, 0)) >= 100000
        ), trade_customers as (
          select distinct pty_id from mart.dwd_cust_tran_d where data_dt between '20260201' and '20260228'
        )
        select count(*) as customer_count
        from asset_customers a join holding_customers h on h.pty_id = a.pty_id
        join trade_customers t on t.pty_id = a.pty_id limit 1
    """, "segment"),
)


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def expected(cursor: Any, sql: str) -> dict[str, Any]:
    cursor.execute(sql)
    columns = [item.name for item in cursor.description]
    rows = [
        {key: jsonable(value) for key, value in zip(columns, row, strict=True)}
        for row in cursor.fetchall()
    ]
    return {"columns": columns, "rows": rows, "row_count": len(rows), "comparison": "unordered"}


def validate() -> None:
    if len(CASES) != 40 or len({item.code for item in CASES}) != 40 or len({item.question for item in CASES}) != 40:
        raise ValueError("The fifth held-out challenge set must contain 40 unique cases.")
    for item in CASES:
        sql = item.sql.lower()
        if "mart." not in sql or " limit " not in sql or ".name" in sql:
            raise ValueError(f"{item.code} is not an official, bounded, non-sensitive query.")


def main() -> None:
    validate()
    connection = engine.raw_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("update evaluation.eval_cases set is_active = false where source_type = %s", (SOURCE_TYPE,))
            for item in CASES:
                result = expected(cursor, item.sql)
                tags = [TAG, "benchmark", item.topic, item.difficulty, item.code.lower()]
                cursor.execute(
                    """
                    insert into evaluation.eval_cases
                        (case_code, question, difficulty, scenario, expected_query_plan, expected_sql,
                         expected_result, scoring_config, dataset_version, source_type, expected_status,
                         tags, is_active)
                    values (%s, %s, %s, 'customer_marketing', %s, %s, %s, %s, %s, %s, 'completed', %s, true)
                    on conflict (case_code) do update set
                        question = excluded.question, difficulty = excluded.difficulty,
                        scenario = excluded.scenario, expected_query_plan = excluded.expected_query_plan,
                        expected_sql = excluded.expected_sql, expected_result = excluded.expected_result,
                        scoring_config = excluded.scoring_config, dataset_version = excluded.dataset_version,
                        source_type = excluded.source_type, expected_status = excluded.expected_status,
                        tags = excluded.tags, is_active = true, updated_at = now()
                    """,
                    (
                        item.code, item.question, item.difficulty,
                        Jsonb({"intent": "metric_query", "scenario": "customer_marketing"}),
                        item.sql, Jsonb(result), Jsonb({"comparison": "unordered", "require_execution": True}),
                        DATASET_VERSION, SOURCE_TYPE, Jsonb(tags),
                    ),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    print(json.dumps({
        "loaded_cases": len(CASES),
        "difficulty_counts": {level: sum(item.difficulty == level for item in CASES) for level in ("simple", "medium", "complex")},
        "source_type": SOURCE_TYPE,
        "is_held_out": True,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
