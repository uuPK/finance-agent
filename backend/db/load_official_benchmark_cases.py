# ruff: noqa: E501
"""Build a reproducible marketing-question benchmark from the official dataset.

The organizer package supplies seven reference Q&A rows.  This script supplements
them with 60 *derived* questions whose SQL is executed against the loaded official
tables at build time.  It never creates customer records or uses the masked name
field, so each expected result remains traceable to the official competition data.

Run from ``backend`` after the official dataset has been loaded::

    .venv\\Scripts\\python.exe db/load_official_benchmark_cases.py
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

DATASET_VERSION = "official-v1"
SOURCE_TYPE = "official_derived"
TAG = "official_derived"
EXTENSION_DATASET_VERSION = "official-v1-extension"
EXTENSION_SOURCE_TYPE = "official_extension"
EXTENSION_TAG = "official_extension"


@dataclass(frozen=True)
class BenchmarkCase:
    code: str
    question: str
    difficulty: str
    sql: str
    topic: str


def _case(no: int, question: str, difficulty: str, sql: str, topic: str) -> BenchmarkCase:
    return BenchmarkCase(f"REG-{no:03d}", question, difficulty, sql.strip(), topic)


def _extension_case(
    no: int, question: str, difficulty: str, sql: str, topic: str
) -> BenchmarkCase:
    return BenchmarkCase(f"EXT-{no:03d}", question, difficulty, sql.strip(), topic)


CASES: tuple[BenchmarkCase, ...] = (
    # 客户画像：只使用官方客户快照，不返回脱敏姓名。
    _case(1, "当前官方客户快照中共有多少位去重客户？", "simple", """
        select count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d
        limit 1
    """, "customer"),
    _case(2, "当前官方客户快照中，30岁以下客户有多少位？", "simple", """
        select count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d
        where cust_age < 30
        limit 1
    """, "customer"),
    _case(3, "当前官方客户快照中，30至49岁客户有多少位？", "simple", """
        select count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d
        where cust_age between 30 and 49
        limit 1
    """, "customer"),
    _case(4, "当前官方客户快照中，50至59岁客户有多少位？", "simple", """
        select count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d
        where cust_age between 50 and 59
        limit 1
    """, "customer"),
    _case(5, "当前官方客户快照中，60岁及以上客户有多少位？", "simple", """
        select count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d
        where cust_age >= 60
        limit 1
    """, "customer"),
    _case(6, "请按性别代码统计当前客户数。", "simple", """
        select gender_cd, count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d
        group by gender_cd
        order by gender_cd
        limit 20
    """, "customer"),
    _case(7, "请按客户状态统计当前客户数。", "simple", """
        select cust_status, count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d
        group by cust_status
        order by customer_count desc, cust_status
        limit 20
    """, "customer"),
    _case(8, "请按客户类型统计当前客户数。", "simple", """
        select cust_type, count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d
        group by cust_type
        order by customer_count desc, cust_type
        limit 20
    """, "customer"),
    _case(9, "请按省份统计当前客户数，按客户数从高到低展示前20个省份。", "medium", """
        select prov_name, count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d
        group by prov_name
        order by customer_count desc, prov_name
        limit 20
    """, "customer"),
    _case(10, "请按城市统计当前客户数，按客户数从高到低展示前20个城市。", "medium", """
        select city_name, count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d
        group by city_name
        order by customer_count desc, city_name
        limit 20
    """, "customer"),
    _case(11, "请按客户等级代码统计当前客户数。", "medium", """
        select cust_lvl_cd, count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d
        group by cust_lvl_cd
        order by customer_count desc, cust_lvl_cd
        limit 20
    """, "customer"),
    _case(12, "请按学历代码统计当前客户数。", "medium", """
        select edu_cd, count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d
        group by edu_cd
        order by customer_count desc, edu_cd
        limit 20
    """, "customer"),
    # 资产画像：资产日期统一取官方数据中的最新资产日期。
    _case(13, "截至最新资产日期，客户总资产合计是多少？", "simple", """
        with latest_asset_date as (
            select max(data_dt) as data_dt from mart.dws_cust_aset_d
        )
        select sum(coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0)) as total_asset
        from mart.dws_cust_aset_d a
        join latest_asset_date d on a.data_dt = d.data_dt
        limit 1
    """, "asset"),
    _case(14, "截至最新资产日期，客户平均总资产是多少？", "simple", """
        with latest_asset_date as (
            select max(data_dt) as data_dt from mart.dws_cust_aset_d
        )
        select avg(coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0)) as average_total_asset
        from mart.dws_cust_aset_d a
        join latest_asset_date d on a.data_dt = d.data_dt
        limit 1
    """, "asset"),
    _case(15, "截至最新资产日期，总资产不少于10万元的客户有多少位？", "simple", """
        with latest_asset_date as (
            select max(data_dt) as data_dt from mart.dws_cust_aset_d
        )
        select count(distinct a.pty_id) as customer_count
        from mart.dws_cust_aset_d a
        join latest_asset_date d on a.data_dt = d.data_dt
        where coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0) >= 100000
        limit 1
    """, "asset"),
    _case(16, "截至最新资产日期，总资产不少于30万元的客户有多少位？", "simple", """
        with latest_asset_date as (
            select max(data_dt) as data_dt from mart.dws_cust_aset_d
        )
        select count(distinct a.pty_id) as customer_count
        from mart.dws_cust_aset_d a
        join latest_asset_date d on a.data_dt = d.data_dt
        where coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0) >= 300000
        limit 1
    """, "asset"),
    _case(17, "截至最新资产日期，请列出总资产最高的20位客户标识及资产金额。", "medium", """
        with latest_asset_date as (
            select max(data_dt) as data_dt from mart.dws_cust_aset_d
        )
        select a.pty_id, coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0) as total_asset
        from mart.dws_cust_aset_d a
        join latest_asset_date d on a.data_dt = d.data_dt
        order by total_asset desc, a.pty_id
        limit 20
    """, "asset"),
    _case(18, "截至最新资产日期，请按省份汇总客户总资产，展示前20个省份。", "medium", """
        with latest_asset_date as (
            select max(data_dt) as data_dt from mart.dws_cust_aset_d
        )
        select c.prov_name,
               sum(coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0)) as total_asset
        from mart.dws_cust_aset_d a
        join latest_asset_date d on a.data_dt = d.data_dt
        join mart.ads_cust_info_d c on c.pty_id = a.pty_id
        group by c.prov_name
        order by total_asset desc, c.prov_name
        limit 20
    """, "asset"),
    _case(19, "截至最新资产日期，请按城市汇总客户总资产，展示前20个城市。", "medium", """
        with latest_asset_date as (
            select max(data_dt) as data_dt from mart.dws_cust_aset_d
        )
        select c.city_name,
               sum(coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0)) as total_asset
        from mart.dws_cust_aset_d a
        join latest_asset_date d on a.data_dt = d.data_dt
        join mart.ads_cust_info_d c on c.pty_id = a.pty_id
        group by c.city_name
        order by total_asset desc, c.city_name
        limit 20
    """, "asset"),
    _case(20, "截至最新资产日期，请按年龄段（30岁以下、30-49岁、50-59岁、60岁及以上）统计客户数和总资产。", "medium", """
        with latest_asset_date as (
            select max(data_dt) as data_dt from mart.dws_cust_aset_d
        )
        select case
                   when c.cust_age < 30 then 'under_30'
                   when c.cust_age between 30 and 49 then 'age_30_49'
                   when c.cust_age between 50 and 59 then 'age_50_59'
                   else 'age_60_plus'
               end as age_group,
               count(distinct a.pty_id) as customer_count,
               sum(coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0)) as total_asset
        from mart.dws_cust_aset_d a
        join latest_asset_date d on a.data_dt = d.data_dt
        join mart.ads_cust_info_d c on c.pty_id = a.pty_id
        group by age_group
        order by age_group
        limit 10
    """, "asset"),
    _case(21, "截至最新资产日期，客户现金资产合计是多少？", "simple", """
        with latest_asset_date as (
            select max(data_dt) as data_dt from mart.dws_cust_aset_d
        )
        select sum(coalesce(a.nm_bal, 0) + coalesce(a.fc_bal, 0)) as cash_asset
        from mart.dws_cust_aset_d a
        join latest_asset_date d on a.data_dt = d.data_dt
        limit 1
    """, "asset"),
    _case(22, "截至最新资产日期，请按客户状态统计总资产不少于30万元的客户数。", "medium", """
        with latest_asset_date as (
            select max(data_dt) as data_dt from mart.dws_cust_aset_d
        )
        select c.cust_status, count(distinct a.pty_id) as customer_count
        from mart.dws_cust_aset_d a
        join latest_asset_date d on a.data_dt = d.data_dt
        join mart.ads_cust_info_d c on c.pty_id = a.pty_id
        where coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0) >= 300000
        group by c.cust_status
        order by customer_count desc, c.cust_status
        limit 20
    """, "asset"),
    _case(23, "截至最新资产日期，请按营业部统计客户总资产，展示前20个营业部。", "medium", """
        with latest_asset_date as (
            select max(data_dt) as data_dt from mart.dws_cust_aset_d
        )
        select b.up_org_name, b.org_name,
               sum(coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0)) as total_asset
        from mart.dws_cust_aset_d a
        join latest_asset_date d on a.data_dt = d.data_dt
        join mart.ads_cust_info_d c on c.pty_id = a.pty_id
        join mart.dim_branch b on b.org_id = c.org_id
        group by b.up_org_name, b.org_name
        order by total_asset desc, b.up_org_name, b.org_name
        limit 20
    """, "asset"),
    _case(24, "截至最新资产日期，请按性别代码统计客户数、平均总资产和总资产。", "medium", """
        with latest_asset_date as (
            select max(data_dt) as data_dt from mart.dws_cust_aset_d
        )
        select c.gender_cd,
               count(distinct a.pty_id) as customer_count,
               avg(coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0)) as average_total_asset,
               sum(coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0)) as total_asset
        from mart.dws_cust_aset_d a
        join latest_asset_date d on a.data_dt = d.data_dt
        join mart.ads_cust_info_d c on c.pty_id = a.pty_id
        group by c.gender_cd
        order by c.gender_cd
        limit 20
    """, "asset"),
    # 交易行为：时间范围固定为官方数据 2026 年第一季度。
    _case(25, "2026年第一季度，客户交易金额合计是多少？", "simple", """
        select sum(coalesce(buy_amt, 0) + coalesce(sell_amt, 0)) as trade_amount
        from mart.dwd_cust_tran_d
        where data_dt between '20260101' and '20260331'
        limit 1
    """, "trade"),
    _case(26, "2026年第一季度，客户买入金额合计是多少？", "simple", """
        select sum(coalesce(buy_amt, 0)) as buy_amount
        from mart.dwd_cust_tran_d
        where data_dt between '20260101' and '20260331'
        limit 1
    """, "trade"),
    _case(27, "2026年第一季度，客户卖出金额合计是多少？", "simple", """
        select sum(coalesce(sell_amt, 0)) as sell_amount
        from mart.dwd_cust_tran_d
        where data_dt between '20260101' and '20260331'
        limit 1
    """, "trade"),
    _case(28, "2026年第一季度，发生过交易的去重客户有多少位？", "simple", """
        select count(distinct pty_id) as customer_count
        from mart.dwd_cust_tran_d
        where data_dt between '20260101' and '20260331'
        limit 1
    """, "trade"),
    _case(29, "2026年第一季度，请按账户来源统计交易金额。", "medium", """
        select sys_source, sum(coalesce(buy_amt, 0) + coalesce(sell_amt, 0)) as trade_amount
        from mart.dwd_cust_tran_d
        where data_dt between '20260101' and '20260331'
        group by sys_source
        order by trade_amount desc, sys_source
        limit 20
    """, "trade"),
    _case(30, "2026年第一季度，请按产品大类统计交易金额，展示前20类。", "medium", """
        select p.up_prdt_type_id, p.up_prdt_type_name,
               sum(coalesce(t.buy_amt, 0) + coalesce(t.sell_amt, 0)) as trade_amount
        from mart.dwd_cust_tran_d t
        join mart.dim_product p on p.prdt_id = t.prdt_id
        where t.data_dt between '20260101' and '20260331'
        group by p.up_prdt_type_id, p.up_prdt_type_name
        order by trade_amount desc, p.up_prdt_type_id, p.up_prdt_type_name
        limit 20
    """, "trade"),
    _case(31, "2026年第一季度，请按产品大类统计买卖笔数，展示前20类。", "medium", """
        select p.up_prdt_type_id, p.up_prdt_type_name,
               sum(coalesce(t.buy_cnt, 0) + coalesce(t.sell_cnt, 0)) as trade_count
        from mart.dwd_cust_tran_d t
        join mart.dim_product p on p.prdt_id = t.prdt_id
        where t.data_dt between '20260101' and '20260331'
        group by p.up_prdt_type_id, p.up_prdt_type_name
        order by trade_count desc, p.up_prdt_type_id, p.up_prdt_type_name
        limit 20
    """, "trade"),
    _case(32, "2026年1月10日至2月15日，客户交易金额合计是多少？", "simple", """
        select sum(coalesce(buy_amt, 0) + coalesce(sell_amt, 0)) as trade_amount
        from mart.dwd_cust_tran_d
        where data_dt between '20260110' and '20260215'
        limit 1
    """, "trade"),
    _case(33, "2026年第一季度，累计交易金额不少于10万元的客户有多少位？", "medium", """
        with customer_trade as (
            select pty_id, sum(coalesce(buy_amt, 0) + coalesce(sell_amt, 0)) as trade_amount
            from mart.dwd_cust_tran_d
            where data_dt between '20260101' and '20260331'
            group by pty_id
        )
        select count(*) as customer_count
        from customer_trade
        where trade_amount >= 100000
        limit 1
    """, "trade"),
    _case(34, "2026年第一季度，累计买卖笔数超过3笔的客户有多少位？", "medium", """
        with customer_trade as (
            select pty_id, sum(coalesce(buy_cnt, 0) + coalesce(sell_cnt, 0)) as trade_count
            from mart.dwd_cust_tran_d
            where data_dt between '20260101' and '20260331'
            group by pty_id
        )
        select count(*) as customer_count
        from customer_trade
        where trade_count > 3
        limit 1
    """, "trade"),
    _case(35, "2026年第一季度，请列出交易金额最高的20只产品。", "medium", """
        select t.prdt_id, p.prdt_name,
               sum(coalesce(t.buy_amt, 0) + coalesce(t.sell_amt, 0)) as trade_amount
        from mart.dwd_cust_tran_d t
        join mart.dim_product p on p.prdt_id = t.prdt_id
        where t.data_dt between '20260101' and '20260331'
        group by t.prdt_id, p.prdt_name
        order by trade_amount desc, t.prdt_id
        limit 20
    """, "trade"),
    _case(36, "2026年第一季度，请列出交易金额最高的20个交易日。", "medium", """
        select data_dt, sum(coalesce(buy_amt, 0) + coalesce(sell_amt, 0)) as trade_amount
        from mart.dwd_cust_tran_d
        where data_dt between '20260101' and '20260331'
        group by data_dt
        order by trade_amount desc, data_dt
        limit 20
    """, "trade"),
    _case(37, "2026年第一季度，请按营业部统计交易金额，展示前20个营业部。", "medium", """
        select b.up_org_name, b.org_name,
               sum(coalesce(t.buy_amt, 0) + coalesce(t.sell_amt, 0)) as trade_amount
        from mart.dwd_cust_tran_d t
        join mart.ads_cust_info_d c on c.pty_id = t.pty_id
        join mart.dim_branch b on b.org_id = c.org_id
        where t.data_dt between '20260101' and '20260331'
        group by b.up_org_name, b.org_name
        order by trade_amount desc, b.up_org_name, b.org_name
        limit 20
    """, "trade"),
    _case(38, "2026年第一季度，请按客户状态统计交易客户数和交易金额。", "medium", """
        select c.cust_status, count(distinct t.pty_id) as customer_count,
               sum(coalesce(t.buy_amt, 0) + coalesce(t.sell_amt, 0)) as trade_amount
        from mart.dwd_cust_tran_d t
        join mart.ads_cust_info_d c on c.pty_id = t.pty_id
        where t.data_dt between '20260101' and '20260331'
        group by c.cust_status
        order by trade_amount desc, c.cust_status
        limit 20
    """, "trade"),
    # 持仓画像：期末统一为 2026-03-31。
    _case(39, "截至2026年3月31日，客户持仓市值合计是多少？", "simple", """
        select sum(coalesce(mkt_val, 0)) as holding_market_value
        from mart.dwd_cust_hold_d
        where data_dt = '20260331'
        limit 1
    """, "holding"),
    _case(40, "截至2026年3月31日，持有产品的去重客户有多少位？", "simple", """
        select count(distinct pty_id) as customer_count
        from mart.dwd_cust_hold_d
        where data_dt = '20260331'
        limit 1
    """, "holding"),
    _case(41, "截至2026年3月31日，请按产品大类统计持仓市值，展示前20类。", "medium", """
        select p.up_prdt_type_id, p.up_prdt_type_name,
               sum(coalesce(h.mkt_val, 0)) as holding_market_value
        from mart.dwd_cust_hold_d h
        join mart.dim_product p on p.prdt_id = h.prdt_id
        where h.data_dt = '20260331'
        group by p.up_prdt_type_id, p.up_prdt_type_name
        order by holding_market_value desc, p.up_prdt_type_id, p.up_prdt_type_name
        limit 20
    """, "holding"),
    _case(42, "截至2026年3月31日，请按产品大类统计持有份额，展示前20类。", "medium", """
        select p.up_prdt_type_id, p.up_prdt_type_name,
               sum(coalesce(h.hold_cnt, 0)) as holding_quantity
        from mart.dwd_cust_hold_d h
        join mart.dim_product p on p.prdt_id = h.prdt_id
        where h.data_dt = '20260331'
        group by p.up_prdt_type_id, p.up_prdt_type_name
        order by holding_quantity desc, p.up_prdt_type_id, p.up_prdt_type_name
        limit 20
    """, "holding"),
    _case(43, "截至2026年3月31日，请列出持仓市值最高的20只产品。", "medium", """
        select h.prdt_id, p.prdt_name, sum(coalesce(h.mkt_val, 0)) as holding_market_value
        from mart.dwd_cust_hold_d h
        join mart.dim_product p on p.prdt_id = h.prdt_id
        where h.data_dt = '20260331'
        group by h.prdt_id, p.prdt_name
        order by holding_market_value desc, h.prdt_id
        limit 20
    """, "holding"),
    _case(44, "截至2026年3月31日，请按账户来源统计持仓市值和持仓客户数。", "medium", """
        select sys_source, count(distinct pty_id) as customer_count,
               sum(coalesce(mkt_val, 0)) as holding_market_value
        from mart.dwd_cust_hold_d
        where data_dt = '20260331'
        group by sys_source
        order by holding_market_value desc, sys_source
        limit 20
    """, "holding"),
    _case(45, "截至2026年3月31日，请按币种统计持仓市值。", "medium", """
        select ccy, sum(coalesce(mkt_val, 0)) as holding_market_value
        from mart.dwd_cust_hold_d
        where data_dt = '20260331'
        group by ccy
        order by holding_market_value desc, ccy
        limit 20
    """, "holding"),
    _case(46, "截至2026年3月31日，持仓市值不少于10万元的客户有多少位？", "medium", """
        with customer_holding as (
            select pty_id, sum(coalesce(mkt_val, 0)) as holding_market_value
            from mart.dwd_cust_hold_d
            where data_dt = '20260331'
            group by pty_id
        )
        select count(*) as customer_count
        from customer_holding
        where holding_market_value >= 100000
        limit 1
    """, "holding"),
    _case(47, "截至2026年3月31日，请按营业部统计持仓市值，展示前20个营业部。", "medium", """
        select b.up_org_name, b.org_name, sum(coalesce(h.mkt_val, 0)) as holding_market_value
        from mart.dwd_cust_hold_d h
        join mart.ads_cust_info_d c on c.pty_id = h.pty_id
        join mart.dim_branch b on b.org_id = c.org_id
        where h.data_dt = '20260331'
        group by b.up_org_name, b.org_name
        order by holding_market_value desc, b.up_org_name, b.org_name
        limit 20
    """, "holding"),
    _case(48, "截至2026年3月31日，请按年龄段统计持仓客户数和持仓市值。", "complex", """
        select case
                   when c.cust_age < 30 then 'under_30'
                   when c.cust_age between 30 and 49 then 'age_30_49'
                   when c.cust_age between 50 and 59 then 'age_50_59'
                   else 'age_60_plus'
               end as age_group,
               count(distinct h.pty_id) as customer_count,
               sum(coalesce(h.mkt_val, 0)) as holding_market_value
        from mart.dwd_cust_hold_d h
        join mart.ads_cust_info_d c on c.pty_id = h.pty_id
        where h.data_dt = '20260331'
        group by age_group
        order by age_group
        limit 10
    """, "holding"),
    # 资金流与营销分群：覆盖多事实表、日期和产品类别的组合口径。
    _case(49, "2026年第一季度，客户净资金流入合计是多少？", "simple", """
        select sum(coalesce(cash_in, 0) + coalesce(tran_in, 0) + coalesce(assign_in, 0)
                   - coalesce(cash_out, 0) - coalesce(tran_out, 0) - coalesce(assign_out, 0)) as net_cash_flow
        from mart.dws_cust_fin_d
        where data_dt between '20260101' and '20260331'
        limit 1
    """, "cash_flow"),
    _case(50, "2026年第一季度，客户现金流入金额合计是多少？", "simple", """
        select sum(coalesce(cash_in, 0)) as cash_in_amount
        from mart.dws_cust_fin_d
        where data_dt between '20260101' and '20260331'
        limit 1
    """, "cash_flow"),
    _case(51, "2026年第一季度，客户现金流出金额合计是多少？", "simple", """
        select sum(coalesce(cash_out, 0)) as cash_out_amount
        from mart.dws_cust_fin_d
        where data_dt between '20260101' and '20260331'
        limit 1
    """, "cash_flow"),
    _case(52, "2026年第一季度，请按账户来源统计净资金流入。", "medium", """
        select sys_source,
               sum(coalesce(cash_in, 0) + coalesce(tran_in, 0) + coalesce(assign_in, 0)
                   - coalesce(cash_out, 0) - coalesce(tran_out, 0) - coalesce(assign_out, 0)) as net_cash_flow
        from mart.dws_cust_fin_d
        where data_dt between '20260101' and '20260331'
        group by sys_source
        order by net_cash_flow desc, sys_source
        limit 20
    """, "cash_flow"),
    _case(53, "2026年第一季度，请按营业部统计净资金流入，展示前20个营业部。", "medium", """
        select b.up_org_name, b.org_name,
               sum(coalesce(f.cash_in, 0) + coalesce(f.tran_in, 0) + coalesce(f.assign_in, 0)
                   - coalesce(f.cash_out, 0) - coalesce(f.tran_out, 0) - coalesce(f.assign_out, 0)) as net_cash_flow
        from mart.dws_cust_fin_d f
        join mart.ads_cust_info_d c on c.pty_id = f.pty_id
        join mart.dim_branch b on b.org_id = c.org_id
        where f.data_dt between '20260101' and '20260331'
        group by b.up_org_name, b.org_name
        order by net_cash_flow desc, b.up_org_name, b.org_name
        limit 20
    """, "cash_flow"),
    _case(54, "2026年第一季度，请列出净资金流入最高的20位客户标识及金额。", "medium", """
        select pty_id,
               sum(coalesce(cash_in, 0) + coalesce(tran_in, 0) + coalesce(assign_in, 0)
                   - coalesce(cash_out, 0) - coalesce(tran_out, 0) - coalesce(assign_out, 0)) as net_cash_flow
        from mart.dws_cust_fin_d
        where data_dt between '20260101' and '20260331'
        group by pty_id
        order by net_cash_flow desc, pty_id
        limit 20
    """, "cash_flow"),
    _case(55, "2026年第一季度，净资金流入为正的客户有多少位？", "medium", """
        with customer_cash_flow as (
            select pty_id,
                   sum(coalesce(cash_in, 0) + coalesce(tran_in, 0) + coalesce(assign_in, 0)
                       - coalesce(cash_out, 0) - coalesce(tran_out, 0) - coalesce(assign_out, 0)) as net_cash_flow
            from mart.dws_cust_fin_d
            where data_dt between '20260101' and '20260331'
            group by pty_id
        )
        select count(*) as customer_count
        from customer_cash_flow
        where net_cash_flow > 0
        limit 1
    """, "cash_flow"),
    _case(56, "截至2026年3月31日总资产不少于30万元且2026年第一季度交易金额不少于10万元的客户有多少位？", "complex", """
        with asset_customer as (
            select pty_id
            from mart.dws_cust_aset_d
            where data_dt = '20260331'
              and coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0) >= 300000
        ), customer_trade as (
            select pty_id
            from mart.dwd_cust_tran_d
            where data_dt between '20260101' and '20260331'
            group by pty_id
            having sum(coalesce(buy_amt, 0) + coalesce(sell_amt, 0)) >= 100000
        )
        select count(*) as customer_count
        from asset_customer a
        join customer_trade t on t.pty_id = a.pty_id
        limit 1
    """, "segment"),
    _case(57, "2026年第一季度发生交易且截至3月31日仍有持仓的客户有多少位？", "complex", """
        with traded_customer as (
            select distinct pty_id
            from mart.dwd_cust_tran_d
            where data_dt between '20260101' and '20260331'
        ), holding_customer as (
            select distinct pty_id
            from mart.dwd_cust_hold_d
            where data_dt = '20260331' and coalesce(mkt_val, 0) > 0
        )
        select count(*) as customer_count
        from traded_customer t
        join holding_customer h on h.pty_id = t.pty_id
        limit 1
    """, "segment"),
    _case(58, "截至3月31日总资产不少于30万元且2026年第一季度股票类产品交易金额不少于10万元的客户有多少位？", "complex", """
        with asset_customer as (
            select pty_id
            from mart.dws_cust_aset_d
            where data_dt = '20260331'
              and coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0) >= 300000
        ), stock_trade_customer as (
            select t.pty_id
            from mart.dwd_cust_tran_d t
            join mart.dim_product p on p.prdt_id = t.prdt_id
            where t.data_dt between '20260101' and '20260331'
              and p.up_prdt_type_id = 'PT040000'
            group by t.pty_id
            having sum(coalesce(t.buy_amt, 0) + coalesce(t.sell_amt, 0)) >= 100000
        )
        select count(*) as customer_count
        from asset_customer a
        join stock_trade_customer t on t.pty_id = a.pty_id
        limit 1
    """, "segment"),
    _case(59, "截至3月31日总资产不少于30万元且第一季度股票类交易金额不少于10万元的客户，持仓产品大类有哪些？", "complex", """
        with target_customer as (
            select a.pty_id
            from mart.dws_cust_aset_d a
            join (
                select t.pty_id
                from mart.dwd_cust_tran_d t
                join mart.dim_product p on p.prdt_id = t.prdt_id
                where t.data_dt between '20260101' and '20260331'
                  and p.up_prdt_type_id = 'PT040000'
                group by t.pty_id
                having sum(coalesce(t.buy_amt, 0) + coalesce(t.sell_amt, 0)) >= 100000
            ) t on t.pty_id = a.pty_id
            where a.data_dt = '20260331'
              and coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0) >= 300000
        )
        select p.up_prdt_type_id, p.up_prdt_type_name,
               count(distinct h.pty_id) as customer_count,
               sum(coalesce(h.mkt_val, 0)) as holding_market_value
        from mart.dwd_cust_hold_d h
        join target_customer c on c.pty_id = h.pty_id
        join mart.dim_product p on p.prdt_id = h.prdt_id
        where h.data_dt = '20260331'
        group by p.up_prdt_type_id, p.up_prdt_type_name
        order by holding_market_value desc, p.up_prdt_type_id, p.up_prdt_type_name
        limit 20
    """, "segment"),
    _case(60, "请按一级营业部、营业部、省份和城市统计当前客户数，展示前200条。", "complex", """
        select b.up_org_name, b.org_name, c.prov_name, c.city_name,
               count(distinct c.pty_id) as customer_count
        from mart.ads_cust_info_d c
        join mart.dim_branch b on b.org_id = c.org_id
        group by b.up_org_name, b.org_name, c.prov_name, c.city_name
        order by customer_count desc, b.up_org_name, b.org_name, c.prov_name, c.city_name
        limit 200
    """, "customer"),
)


# Held-out extension set.  These are evaluated against the same official tables but are
# deliberately not inserted into metadata.question_examples, so the Agent cannot retrieve
# an exact question/SQL pair during this generalization check.
EXTENSION_CASES: tuple[BenchmarkCase, ...] = (
    _extension_case(1, "当前官方客户快照中，客户平均年龄是多少？", "simple", """
        select avg(cust_age) as average_customer_age
        from mart.ads_cust_info_d
        limit 1
    """, "customer"),
    _extension_case(2, "当前官方客户快照中，年龄不低于40岁的去重客户有多少位？", "simple", """
        select count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d
        where cust_age >= 40
        limit 1
    """, "customer"),
    _extension_case(3, "请按性别代码和客户状态统计当前客户数。", "medium", """
        select gender_cd, cust_status, count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d
        group by gender_cd, cust_status
        order by customer_count desc, gender_cd, cust_status
        limit 50
    """, "customer"),
    _extension_case(4, "请按客户等级代码统计当前客户数和平均年龄。", "medium", """
        select cust_lvl_cd, count(distinct pty_id) as customer_count,
               avg(cust_age) as average_customer_age
        from mart.ads_cust_info_d
        group by cust_lvl_cd
        order by customer_count desc, cust_lvl_cd
        limit 20
    """, "customer"),
    _extension_case(5, "请按一级营业部统计当前客户数，展示前20个一级营业部。", "medium", """
        select b.up_org_name, count(distinct c.pty_id) as customer_count
        from mart.ads_cust_info_d c
        join mart.dim_branch b on b.org_id = c.org_id
        group by b.up_org_name
        order by customer_count desc, b.up_org_name
        limit 20
    """, "customer"),
    _extension_case(6, "当前官方客户快照中，已分配营业部的去重客户有多少位？", "simple", """
        select count(distinct pty_id) as customer_count
        from mart.ads_cust_info_d
        where org_id is not null and org_id <> ''
        limit 1
    """, "customer"),
    _extension_case(7, "截至2026年3月31日，普通账户总资产合计是多少？", "simple", """
        select sum(coalesce(nm_tot_aset, 0)) as normal_total_asset
        from mart.dws_cust_aset_d
        where data_dt = '20260331'
        limit 1
    """, "asset"),
    _extension_case(8, "截至2026年3月31日，信用账户净资产合计是多少？", "simple", """
        select sum(coalesce(fc_pur_aset, 0)) as credit_total_asset
        from mart.dws_cust_aset_d
        where data_dt = '20260331'
        limit 1
    """, "asset"),
    _extension_case(9, "截至2026年3月31日，总资产低于10万元的客户有多少位？", "simple", """
        select count(distinct pty_id) as customer_count
        from mart.dws_cust_aset_d
        where data_dt = '20260331'
          and coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0) < 100000
        limit 1
    """, "asset"),
    _extension_case(10, "截至2026年3月31日，请按客户类型统计客户数和总资产。", "medium", """
        select c.cust_type, count(distinct a.pty_id) as customer_count,
               sum(coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0)) as total_asset
        from mart.dws_cust_aset_d a
        join mart.ads_cust_info_d c on c.pty_id = a.pty_id
        where a.data_dt = '20260331'
        group by c.cust_type
        order by total_asset desc, c.cust_type
        limit 20
    """, "asset"),
    _extension_case(11, "截至2026年3月31日，请按客户等级代码汇总客户总资产，展示前20个等级。", "medium", """
        select c.cust_lvl_cd,
               sum(coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0)) as total_asset
        from mart.dws_cust_aset_d a
        join mart.ads_cust_info_d c on c.pty_id = a.pty_id
        where a.data_dt = '20260331'
        group by c.cust_lvl_cd
        order by total_asset desc, c.cust_lvl_cd
        limit 20
    """, "asset"),
    _extension_case(12, "截至2026年3月31日，请按一级营业部汇总客户总资产，展示前20个一级营业部。", "medium", """
        select b.up_org_name,
               sum(coalesce(a.nm_tot_aset, 0) + coalesce(a.fc_pur_aset, 0)) as total_asset
        from mart.dws_cust_aset_d a
        join mart.ads_cust_info_d c on c.pty_id = a.pty_id
        join mart.dim_branch b on b.org_id = c.org_id
        where a.data_dt = '20260331'
        group by b.up_org_name
        order by total_asset desc, b.up_org_name
        limit 20
    """, "asset"),
    _extension_case(13, "2026年第一季度，客户买入金额和卖出金额分别是多少？", "simple", """
        select sum(coalesce(buy_amt, 0)) as buy_amount,
               sum(coalesce(sell_amt, 0)) as sell_amount
        from mart.dwd_cust_tran_d
        where data_dt between '20260101' and '20260331'
        limit 1
    """, "trade"),
    _extension_case(14, "2026年第一季度，客户交易费用合计是多少？", "simple", """
        select sum(coalesce(buy_fare, 0) + coalesce(sell_fare, 0)) as trade_fee
        from mart.dwd_cust_tran_d
        where data_dt between '20260101' and '20260331'
        limit 1
    """, "trade"),
    _extension_case(15, "2026年第一季度，客户成交数量合计是多少？", "simple", """
        select sum(coalesce(buy_mnt, 0) + coalesce(sell_mnt, 0)) as trade_quantity
        from mart.dwd_cust_tran_d
        where data_dt between '20260101' and '20260331'
        limit 1
    """, "trade"),
    _extension_case(16, "2026年第一季度，请按币种统计交易金额。", "medium", """
        select ccy, sum(coalesce(buy_amt, 0) + coalesce(sell_amt, 0)) as trade_amount
        from mart.dwd_cust_tran_d
        where data_dt between '20260101' and '20260331'
        group by ccy
        order by trade_amount desc, ccy
        limit 20
    """, "trade"),
    _extension_case(17, "2026年3月，客户交易金额合计是多少？", "simple", """
        select sum(coalesce(buy_amt, 0) + coalesce(sell_amt, 0)) as trade_amount
        from mart.dwd_cust_tran_d
        where data_dt between '20260301' and '20260331'
        limit 1
    """, "trade"),
    _extension_case(18, "2026年第一季度，同时发生过买入和卖出的去重客户有多少位？", "medium", """
        select count(*) as customer_count
        from (
            select pty_id
            from mart.dwd_cust_tran_d
            where data_dt between '20260101' and '20260331'
            group by pty_id
            having sum(coalesce(buy_amt, 0)) > 0 and sum(coalesce(sell_amt, 0)) > 0
        ) customer_trade
        limit 1
    """, "trade"),
    _extension_case(19, "截至2026年3月31日，请按币种统计持仓客户数和持仓市值。", "medium", """
        select ccy, count(distinct pty_id) as customer_count,
               sum(coalesce(mkt_val, 0)) as holding_market_value
        from mart.dwd_cust_hold_d
        where data_dt = '20260331'
        group by ccy
        order by holding_market_value desc, ccy
        limit 20
    """, "holding"),
    _extension_case(20, "截至2026年3月31日，请列出持有份额最高的20只产品。", "medium", """
        select h.prdt_id, p.prdt_name, sum(coalesce(h.hold_cnt, 0)) as holding_quantity
        from mart.dwd_cust_hold_d h
        join mart.dim_product p on p.prdt_id = h.prdt_id
        where h.data_dt = '20260331'
        group by h.prdt_id, p.prdt_name
        order by holding_quantity desc, h.prdt_id
        limit 20
    """, "holding"),
    _extension_case(21, "截至2026年3月31日，请按产品市场统计持仓市值。", "medium", """
        select p.market_id, sum(coalesce(h.mkt_val, 0)) as holding_market_value
        from mart.dwd_cust_hold_d h
        join mart.dim_product p on p.prdt_id = h.prdt_id
        where h.data_dt = '20260331'
        group by p.market_id
        order by holding_market_value desc, p.market_id
        limit 20
    """, "holding"),
    _extension_case(22, "截至2026年3月31日，持有至少两只不同产品的客户有多少位？", "medium", """
        select count(*) as customer_count
        from (
            select pty_id
            from mart.dwd_cust_hold_d
            where data_dt = '20260331'
            group by pty_id
            having count(distinct prdt_id) >= 2
        ) customer_holding
        limit 1
    """, "holding"),
    _extension_case(23, "2026年第一季度，客户现金净流入合计是多少？", "simple", """
        select sum(coalesce(cash_in, 0) - coalesce(cash_out, 0)) as net_cash_inflow
        from mart.dws_cust_fin_d
        where data_dt between '20260101' and '20260331'
        limit 1
    """, "cash_flow"),
    _extension_case(24, "2026年第一季度，客户转账金额合计是多少？", "simple", """
        select sum(coalesce(tran_in, 0) + coalesce(tran_out, 0)) as transfer_amount
        from mart.dws_cust_fin_d
        where data_dt between '20260101' and '20260331'
        limit 1
    """, "cash_flow"),
    _extension_case(25, "2026年第一季度，客户划拨金额合计是多少？", "simple", """
        select sum(coalesce(assign_in, 0) + coalesce(assign_out, 0)) as assignment_amount
        from mart.dws_cust_fin_d
        where data_dt between '20260101' and '20260331'
        limit 1
    """, "cash_flow"),
    _extension_case(26, "2026年第一季度，有资金流水记录的去重客户有多少位？", "simple", """
        select count(distinct pty_id) as customer_count
        from mart.dws_cust_fin_d
        where data_dt between '20260101' and '20260331'
        limit 1
    """, "cash_flow"),
    _extension_case(27, "截至2026年3月31日总资产不少于30万元且第一季度净资金流入为正的客户有多少位？", "complex", """
        with asset_customer as (
            select pty_id
            from mart.dws_cust_aset_d
            where data_dt = '20260331'
              and coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0) >= 300000
        ), positive_cash_customer as (
            select pty_id
            from mart.dws_cust_fin_d
            where data_dt between '20260101' and '20260331'
            group by pty_id
            having sum(coalesce(cash_in, 0) + coalesce(tran_in, 0) + coalesce(assign_in, 0)
                       - coalesce(cash_out, 0) - coalesce(tran_out, 0) - coalesce(assign_out, 0)) > 0
        )
        select count(*) as customer_count
        from asset_customer a
        join positive_cash_customer f on f.pty_id = a.pty_id
        limit 1
    """, "segment"),
    _extension_case(28, "截至2026年3月31日总资产不少于10万元且持仓市值不少于10万元的客户有多少位？", "complex", """
        with asset_customer as (
            select pty_id
            from mart.dws_cust_aset_d
            where data_dt = '20260331'
              and coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0) >= 100000
        ), holding_customer as (
            select pty_id
            from mart.dwd_cust_hold_d
            where data_dt = '20260331'
            group by pty_id
            having sum(coalesce(mkt_val, 0)) >= 100000
        )
        select count(*) as customer_count
        from asset_customer a
        join holding_customer h on h.pty_id = a.pty_id
        limit 1
    """, "segment"),
    _extension_case(29, "2026年第一季度发生股票类交易且截至3月31日仍有持仓的客户有多少位？", "complex", """
        with stock_trade_customer as (
            select distinct t.pty_id
            from mart.dwd_cust_tran_d t
            join mart.dim_product p on p.prdt_id = t.prdt_id
            where t.data_dt between '20260101' and '20260331'
              and p.up_prdt_type_id = 'PT040000'
        ), holding_customer as (
            select distinct pty_id
            from mart.dwd_cust_hold_d
            where data_dt = '20260331' and coalesce(mkt_val, 0) > 0
        )
        select count(*) as customer_count
        from stock_trade_customer t
        join holding_customer h on h.pty_id = t.pty_id
        limit 1
    """, "segment"),
    _extension_case(30, "截至2026年3月31日，请按客户状态统计总资产不少于10万元客户的客户数和持仓市值。", "complex", """
        with asset_customer as (
            select pty_id
            from mart.dws_cust_aset_d
            where data_dt = '20260331'
              and coalesce(nm_tot_aset, 0) + coalesce(fc_pur_aset, 0) >= 100000
        )
        select c.cust_status, count(distinct a.pty_id) as customer_count,
               sum(coalesce(h.mkt_val, 0)) as holding_market_value
        from asset_customer a
        join mart.ads_cust_info_d c on c.pty_id = a.pty_id
        left join mart.dwd_cust_hold_d h on h.pty_id = a.pty_id and h.data_dt = '20260331'
        group by c.cust_status
        order by holding_market_value desc nulls last, c.cust_status
        limit 20
    """, "segment"),
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _result_payload(cursor: Any, sql: str) -> dict[str, Any]:
    cursor.execute(sql)
    columns = [item.name for item in cursor.description]
    rows = [
        {column: _jsonable(value) for column, value in zip(columns, row, strict=True)}
        for row in cursor.fetchall()
    ]
    return {"columns": columns, "rows": rows, "row_count": len(rows), "comparison": "unordered"}


def _validate_cases() -> None:
    if len(CASES) < 50:
        raise ValueError("The official regression bank must contain at least 50 cases.")
    if len(EXTENSION_CASES) != 30:
        raise ValueError("The held-out official extension must contain exactly 30 cases.")
    all_cases = CASES + EXTENSION_CASES
    codes = [case.code for case in all_cases]
    questions = [case.question for case in all_cases]
    if len(codes) != len(set(codes)) or len(questions) != len(set(questions)):
        raise ValueError("Benchmark case codes and questions must be unique.")
    for case in all_cases:
        sql = case.sql.lower()
        if "mart." not in sql or " limit " not in sql or ".name" in sql:
            raise ValueError(f"{case.code} is not an official, bounded, non-sensitive query.")


def main() -> None:
    _validate_cases()
    raw_connection = engine.raw_connection()
    try:
        with raw_connection.cursor() as cursor:
            case_sets = (
                (CASES, DATASET_VERSION, SOURCE_TYPE, TAG, True),
                (
                    EXTENSION_CASES,
                    EXTENSION_DATASET_VERSION,
                    EXTENSION_SOURCE_TYPE,
                    EXTENSION_TAG,
                    False,
                ),
            )
            # Keep historic evaluation rows intact; only the reproducible official
            # derived bank and its held-out extension rows are refreshed.
            for _, _, source_type, tag, include_as_retrieval_example in case_sets:
                cursor.execute(
                    "update evaluation.eval_cases set is_active = false where source_type = %s",
                    (source_type,),
                )
                if include_as_retrieval_example:
                    cursor.execute(
                        "delete from metadata.question_examples where tags @> %s::jsonb",
                        (Jsonb([tag]),),
                    )

            for cases, dataset_version, source_type, tag, include_as_retrieval_example in case_sets:
                for case in cases:
                    expected_result = _result_payload(cursor, case.sql)
                    tags = [tag, "benchmark", case.topic, case.difficulty, case.code.lower()]
                    expected_plan = {"intent": "metric_query", "scenario": "customer_marketing"}
                    if include_as_retrieval_example:
                        cursor.execute(
                            """
                            insert into metadata.question_examples
                                (question, difficulty, scenario, expected_query_plan, expected_sql,
                                 expected_result, tags)
                            values (%s, %s, 'customer_marketing', %s, %s, %s, %s)
                            """,
                            (
                                case.question,
                                case.difficulty,
                                Jsonb(expected_plan),
                                case.sql,
                                Jsonb(expected_result),
                                Jsonb(tags),
                            ),
                        )
                    cursor.execute(
                        """
                        insert into evaluation.eval_cases
                            (case_code, question, difficulty, scenario, expected_query_plan, expected_sql,
                             expected_result, scoring_config, dataset_version, source_type, expected_status,
                             tags, is_active)
                        values (%s, %s, %s, 'customer_marketing', %s, %s, %s, %s, %s, %s, 'completed', %s, true)
                        on conflict (case_code) do update set
                            question = excluded.question,
                            difficulty = excluded.difficulty,
                            scenario = excluded.scenario,
                            expected_query_plan = excluded.expected_query_plan,
                            expected_sql = excluded.expected_sql,
                            expected_result = excluded.expected_result,
                            scoring_config = excluded.scoring_config,
                            dataset_version = excluded.dataset_version,
                            source_type = excluded.source_type,
                            expected_status = excluded.expected_status,
                            tags = excluded.tags,
                            is_active = true,
                            updated_at = now()
                        """,
                        (
                            case.code,
                            case.question,
                            case.difficulty,
                            Jsonb(expected_plan),
                            case.sql,
                            Jsonb(expected_result),
                            Jsonb({"comparison": "unordered", "require_execution": True}),
                            dataset_version,
                            source_type,
                            Jsonb(tags),
                        ),
                    )
        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        raw_connection.close()

    difficulty_counts = {
        difficulty: sum(case.difficulty == difficulty for case in CASES)
        for difficulty in ("simple", "medium", "complex")
    }
    extension_difficulty_counts = {
        difficulty: sum(case.difficulty == difficulty for case in EXTENSION_CASES)
        for difficulty in ("simple", "medium", "complex")
    }
    print(
        json.dumps(
            {
                "loaded_cases": len(CASES),
                "difficulty_counts": difficulty_counts,
                "source_type": SOURCE_TYPE,
                "loaded_extension_cases": len(EXTENSION_CASES),
                "extension_difficulty_counts": extension_difficulty_counts,
                "extension_source_type": EXTENSION_SOURCE_TYPE,
                "extension_is_held_out": True,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
