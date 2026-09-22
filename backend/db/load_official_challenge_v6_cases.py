# ruff: noqa: E401, E501, E701, E702, I001
"""Load the sixth 30-case held-out challenge set from official tables."""
from __future__ import annotations
import json, sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from psycopg.types.json import Jsonb
if __package__ in {None, ""}: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.session import engine
DATASET_VERSION, SOURCE_TYPE, TAG = "official-v1-challenge-v6", "official_challenge_v6", "official_challenge_v6"
@dataclass(frozen=True)
class Case: code: str; question: str; difficulty: str; sql: str; topic: str
def c(n: int, q: str, d: str, s: str, t: str) -> Case: return Case(f"V6-{n:03d}", q, d, s.strip(), t)
CASES = (
 c(1,"当前客户快照中，女性去重客户有多少位？","simple","select count(distinct pty_id) as customer_count from mart.ads_cust_info_d where gender_cd = '5000003' limit 1","customer"),
 c(2,"当前客户快照中，年龄在45至55岁之间的去重客户有多少位？","simple","select count(distinct pty_id) as customer_count from mart.ads_cust_info_d where cust_age between 45 and 55 limit 1","customer"),
 c(3,"请按学历代码统计当前客户平均年龄，展示前10组。","medium","select edu_cd, avg(cust_age) as average_customer_age from mart.ads_cust_info_d group by edu_cd order by average_customer_age desc nulls last, edu_cd limit 10","customer"),
 c(4,"请按客户状态和客户等级代码统计当前客户数量，展示前20组。","medium","select cust_status, cust_lvl_cd, count(distinct pty_id) as customer_count from mart.ads_cust_info_d group by cust_status, cust_lvl_cd order by customer_count desc, cust_status, cust_lvl_cd limit 20","customer"),
 c(5,"请按城市统计当前女性客户数量，展示前10个城市。","medium","select city_name, count(distinct pty_id) as customer_count from mart.ads_cust_info_d where gender_cd = '5000003' group by city_name order by customer_count desc, city_name limit 10","customer"),
 c(6,"截至2026年3月1日，客户总资产合计是多少？","simple","select sum(coalesce(nm_tot_aset,0)+coalesce(fc_pur_aset,0)) as total_asset from mart.dws_cust_aset_d where data_dt='20260301' limit 1","asset"),
 c(7,"截至2026年3月1日，请按客户状态统计现金资产，展示前10个状态。","medium","select c.cust_status, sum(coalesce(a.nm_bal,0)+coalesce(a.fc_bal,0)) as cash_asset from mart.dws_cust_aset_d a join mart.ads_cust_info_d c on c.pty_id=a.pty_id where a.data_dt='20260301' group by c.cust_status order by cash_asset desc,c.cust_status limit 10","asset"),
 c(8,"截至2026年3月1日，请按省份统计总资产达到50万元的客户数，展示前10个省份。","medium","select c.prov_name,count(distinct a.pty_id) as customer_count from mart.dws_cust_aset_d a join mart.ads_cust_info_d c on c.pty_id=a.pty_id where a.data_dt='20260301' and coalesce(a.nm_tot_aset,0)+coalesce(a.fc_pur_aset,0)>=500000 group by c.prov_name order by customer_count desc,c.prov_name limit 10","asset"),
 c(9,"2026年3月1日至15日，客户现金流入金额合计是多少？","simple","select sum(coalesce(cash_in,0)) as cash_in_amount from mart.dws_cust_fin_d where data_dt between '20260301' and '20260315' limit 1","cash_flow"),
 c(10,"2026年3月1日至15日，请按客户类型统计现金流入金额，展示前10类。","medium","select c.cust_type,sum(coalesce(f.cash_in,0)) as cash_in_amount from mart.dws_cust_fin_d f join mart.ads_cust_info_d c on c.pty_id=f.pty_id where f.data_dt between '20260301' and '20260315' group by c.cust_type order by cash_in_amount desc,c.cust_type limit 10","cash_flow"),
 c(11,"2026年3月1日至15日，累计现金流入达到5万元的客户有多少位？","medium","select count(*) as customer_count from (select pty_id from mart.dws_cust_fin_d where data_dt between '20260301' and '20260315' group by pty_id having sum(coalesce(cash_in,0))>=50000) x limit 1","cash_flow"),
 c(12,"2026年3月1日至15日，发生交易客户的平均交易金额是多少？","complex","select avg(trade_amount) as average_trade_amount from (select pty_id,sum(coalesce(buy_amt,0)+coalesce(sell_amt,0)) as trade_amount from mart.dwd_cust_tran_d where data_dt between '20260301' and '20260315' group by pty_id) x limit 1","trade"),
 c(13,"2026年3月1日至15日，请按币种统计交易费用，展示前10种币种。","medium","select ccy,sum(coalesce(buy_fare,0)+coalesce(sell_fare,0)) as trade_fee from mart.dwd_cust_tran_d where data_dt between '20260301' and '20260315' group by ccy order by trade_fee desc,ccy limit 10","trade"),
 c(14,"2026年3月1日至15日，请按一级营业部统计买入金额，展示前10个营业部。","complex","select b.up_org_name,sum(coalesce(t.buy_amt,0)) as buy_amount from mart.dwd_cust_tran_d t join mart.ads_cust_info_d c on c.pty_id=t.pty_id join mart.dim_branch b on b.org_id=c.org_id where t.data_dt between '20260301' and '20260315' group by b.up_org_name order by buy_amount desc,b.up_org_name limit 10","trade"),
 c(15,"2026年3月1日至15日，累计交易费用大于零的客户有多少位？","medium","select count(*) as customer_count from (select pty_id from mart.dwd_cust_tran_d where data_dt between '20260301' and '20260315' group by pty_id having sum(coalesce(buy_fare,0)+coalesce(sell_fare,0))>0) x limit 1","trade"),
 c(16,"截至2026年3月1日，客户持有份额总量是多少？","simple","select sum(coalesce(hold_cnt,0)) as holding_quantity from mart.dwd_cust_hold_d where data_dt='20260301' limit 1","holding"),
 c(17,"截至2026年3月1日，请按一级产品分类统计持仓市值，展示前10类。","medium","select p.up_prdt_type_name,sum(coalesce(h.mkt_val,0)) as holding_market_value from mart.dwd_cust_hold_d h join mart.dim_product p on p.prdt_id=h.prdt_id where h.data_dt='20260301' group by p.up_prdt_type_name order by holding_market_value desc,p.up_prdt_type_name limit 10","holding"),
 c(18,"截至2026年3月1日，请按客户状态统计持仓客户数，展示前10个状态。","medium","select c.cust_status,count(distinct h.pty_id) as customer_count from mart.dwd_cust_hold_d h join mart.ads_cust_info_d c on c.pty_id=h.pty_id where h.data_dt='20260301' group by c.cust_status order by customer_count desc,c.cust_status limit 10","holding"),
 c(19,"截至2026年3月1日，持仓市值达到30万元的客户有多少位？","simple","select count(*) as customer_count from (select pty_id from mart.dwd_cust_hold_d where data_dt='20260301' group by pty_id having sum(coalesce(mkt_val,0))>=300000) x limit 1","holding"),
 c(20,"截至2026年3月1日，请按产品市场统计持有份额，展示前10个市场。","medium","select p.market_id,sum(coalesce(h.hold_cnt,0)) as holding_quantity from mart.dwd_cust_hold_d h join mart.dim_product p on p.prdt_id=h.prdt_id where h.data_dt='20260301' group by p.market_id order by holding_quantity desc,p.market_id limit 10","holding"),
 c(21,"2026年3月1日至15日，客户净资金流入合计是多少？","simple","select sum(coalesce(cash_in,0)+coalesce(tran_in,0)+coalesce(assign_in,0)-coalesce(cash_out,0)-coalesce(tran_out,0)-coalesce(assign_out,0)) as net_cash_flow from mart.dws_cust_fin_d where data_dt between '20260301' and '20260315' limit 1","cash_flow"),
 c(22,"2026年3月1日至15日，请按省份统计转账金额，展示前10个省份。","complex","select c.prov_name,sum(coalesce(f.tran_in,0)+coalesce(f.tran_out,0)) as transfer_amount from mart.dws_cust_fin_d f join mart.ads_cust_info_d c on c.pty_id=f.pty_id where f.data_dt between '20260301' and '20260315' group by c.prov_name order by transfer_amount desc,c.prov_name limit 10","cash_flow"),
 c(23,"2026年3月1日至15日，现金净流入为正的客户有多少位？","medium","select count(*) as customer_count from (select pty_id from mart.dws_cust_fin_d where data_dt between '20260301' and '20260315' group by pty_id having sum(coalesce(cash_in,0)-coalesce(cash_out,0))>0) x limit 1","cash_flow"),
 c(24,"截至2026年3月1日总资产达到20万元且3月1日至15日发生交易的客户有多少位？","complex","with a as (select pty_id from mart.dws_cust_aset_d where data_dt='20260301' and coalesce(nm_tot_aset,0)+coalesce(fc_pur_aset,0)>=200000), t as (select distinct pty_id from mart.dwd_cust_tran_d where data_dt between '20260301' and '20260315') select count(*) as customer_count from a join t using(pty_id) limit 1","segment"),
 c(25,"截至2026年3月1日，请按客户类型统计总资产和持仓市值，展示前10类。","complex","with a as (select pty_id,sum(coalesce(nm_tot_aset,0)+coalesce(fc_pur_aset,0)) total_asset from mart.dws_cust_aset_d where data_dt='20260301' group by pty_id),h as (select pty_id,sum(coalesce(mkt_val,0)) holding_market_value from mart.dwd_cust_hold_d where data_dt='20260301' group by pty_id) select c.cust_type,sum(a.total_asset) total_asset,sum(coalesce(h.holding_market_value,0)) holding_market_value from a join mart.ads_cust_info_d c on c.pty_id=a.pty_id left join h on h.pty_id=a.pty_id group by c.cust_type order by total_asset desc,c.cust_type limit 10","segment"),
 c(26,"2026年3月1日至15日，请按一级营业部统计交易金额和现金流入金额，展示前10个营业部。","complex","with t as (select pty_id,sum(coalesce(buy_amt,0)+coalesce(sell_amt,0)) trade_amount from mart.dwd_cust_tran_d where data_dt between '20260301' and '20260315' group by pty_id),f as (select pty_id,sum(coalesce(cash_in,0)) cash_in_amount from mart.dws_cust_fin_d where data_dt between '20260301' and '20260315' group by pty_id) select b.up_org_name,sum(t.trade_amount) trade_amount,sum(coalesce(f.cash_in_amount,0)) cash_in_amount from t join mart.ads_cust_info_d c on c.pty_id=t.pty_id join mart.dim_branch b on b.org_id=c.org_id left join f on f.pty_id=t.pty_id group by b.up_org_name order by trade_amount desc,b.up_org_name limit 10","segment"),
 c(27,"截至2026年3月1日持有至少两种不同产品且3月1日至15日现金流入达到5万元的客户有多少位？","complex","with h as (select pty_id from mart.dwd_cust_hold_d where data_dt='20260301' group by pty_id having count(distinct prdt_id)>=2),f as (select pty_id from mart.dws_cust_fin_d where data_dt between '20260301' and '20260315' group by pty_id having sum(coalesce(cash_in,0))>=50000) select count(*) as customer_count from h join f using(pty_id) limit 1","segment"),
 c(28,"截至2026年3月1日，请按一级产品分类统计持仓客户数和3月1日至15日交易客户数，展示前10类。","complex","with h as (select p.up_prdt_type_name,count(distinct d.pty_id) holding_customer_count from mart.dwd_cust_hold_d d join mart.dim_product p on p.prdt_id=d.prdt_id where d.data_dt='20260301' group by p.up_prdt_type_name),t as (select p.up_prdt_type_name,count(distinct d.pty_id) trade_customer_count from mart.dwd_cust_tran_d d join mart.dim_product p on p.prdt_id=d.prdt_id where d.data_dt between '20260301' and '20260315' group by p.up_prdt_type_name) select h.up_prdt_type_name,h.holding_customer_count,coalesce(t.trade_customer_count,0) trade_customer_count from h left join t using(up_prdt_type_name) order by h.holding_customer_count desc,h.up_prdt_type_name limit 10","segment"),
 c(29,"3月1日至15日发生股票类交易且截至3月1日总资产达到20万元的客户有多少位？","complex","with a as (select pty_id from mart.dws_cust_aset_d where data_dt='20260301' and coalesce(nm_tot_aset,0)+coalesce(fc_pur_aset,0)>=200000),t as (select distinct d.pty_id from mart.dwd_cust_tran_d d join mart.dim_product p on p.prdt_id=d.prdt_id where d.data_dt between '20260301' and '20260315' and p.up_prdt_type_id='PT040000') select count(*) as customer_count from a join t using(pty_id) limit 1","segment"),
 c(30,"截至2026年3月1日总资产达到20万元、持仓市值达到10万元且3月1日至15日现金净流入为正的客户有多少位？","complex","with a as (select pty_id from mart.dws_cust_aset_d where data_dt='20260301' and coalesce(nm_tot_aset,0)+coalesce(fc_pur_aset,0)>=200000),h as (select pty_id from mart.dwd_cust_hold_d where data_dt='20260301' group by pty_id having sum(coalesce(mkt_val,0))>=100000),f as (select pty_id from mart.dws_cust_fin_d where data_dt between '20260301' and '20260315' group by pty_id having sum(coalesce(cash_in,0)-coalesce(cash_out,0))>0) select count(*) as customer_count from a join h using(pty_id) join f using(pty_id) limit 1","segment"),
)
def val(x: Any) -> Any: return float(x) if isinstance(x,Decimal) else x.isoformat() if isinstance(x,(date,datetime)) else x
def validate() -> None:
 if len(CASES)!=30 or len({x.code for x in CASES})!=30 or len({x.question for x in CASES})!=30: raise ValueError("V6 needs 30 unique cases.")
 if any("mart." not in x.sql.lower() or " limit " not in x.sql.lower() or ".name" in x.sql.lower() for x in CASES): raise ValueError("Unsafe V6 SQL.")
def main() -> None:
 validate(); conn=engine.raw_connection()
 try:
  with conn.cursor() as cur:
   cur.execute("update evaluation.eval_cases set is_active=false where source_type=%s",(SOURCE_TYPE,))
   for x in CASES:
    cur.execute(x.sql); cols=[d.name for d in cur.description]; rows=[{k:val(v) for k,v in zip(cols,row,strict=True)} for row in cur.fetchall()]
    result={"columns":cols,"rows":rows,"row_count":len(rows),"comparison":"unordered"}; tags=[TAG,"benchmark",x.topic,x.difficulty,x.code.lower()]
    cur.execute("""insert into evaluation.eval_cases(case_code,question,difficulty,scenario,expected_query_plan,expected_sql,expected_result,scoring_config,dataset_version,source_type,expected_status,tags,is_active) values(%s,%s,%s,'customer_marketing',%s,%s,%s,%s,%s,%s,'completed',%s,true) on conflict(case_code) do update set question=excluded.question,difficulty=excluded.difficulty,expected_query_plan=excluded.expected_query_plan,expected_sql=excluded.expected_sql,expected_result=excluded.expected_result,scoring_config=excluded.scoring_config,dataset_version=excluded.dataset_version,source_type=excluded.source_type,tags=excluded.tags,is_active=true,updated_at=now()""",(x.code,x.question,x.difficulty,Jsonb({"intent":"metric_query","scenario":"customer_marketing"}),x.sql,Jsonb(result),Jsonb({"comparison":"unordered","require_execution":True}),DATASET_VERSION,SOURCE_TYPE,Jsonb(tags)))
  conn.commit()
 except Exception: conn.rollback(); raise
 finally: conn.close()
 print(json.dumps({"loaded_cases":30,"source_type":SOURCE_TYPE},ensure_ascii=False))
if __name__=="__main__": main()
