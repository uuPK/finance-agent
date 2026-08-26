"""Load the official Huatai competition package into the Finance Agent database.

The loader intentionally keeps the organizer's table and column names.  It imports the
eight supplied CSV files, rebuilds AI metadata from the supplied SQL data dictionary, and
turns every row in Q&A.xlsx into an executable evaluation case with an expected result set.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from psycopg.types.json import Jsonb

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import engine

DATASET_VERSION = "official-v1"
SOURCE_TYPE = "official"

OFFICIAL_TABLES: dict[str, str] = {
    "ads_cust_info_d": "ads_cust_info_d_*.csv",
    "dim_branch": "dim_branch_*.csv",
    "dim_product": "dim_product_*.csv",
    "dim_public": "dim_public_*.csv",
    "dwd_cust_hold_d": "dwd_cust_hold_d_*.csv",
    "dwd_cust_tran_d": "dwd_cust_tran_d_*.csv",
    "dws_cust_aset_d": "dws_cust_aset_d_*.csv",
    "dws_cust_fin_d": "dws_cust_fin_d_*.csv",
}

TABLE_DETAILS: dict[str, dict[str, str]] = {
    "ads_cust_info_d": {"domain": "customer", "grain": "customer-date"},
    "dim_branch": {"domain": "branch", "grain": "branch-date"},
    "dim_product": {"domain": "product", "grain": "product"},
    "dim_public": {"domain": "dimension", "grain": "code-type"},
    "dwd_cust_hold_d": {"domain": "holding", "grain": "customer-product-date-source-currency"},
    "dwd_cust_tran_d": {"domain": "trade", "grain": "customer-product-date-source-currency"},
    "dws_cust_aset_d": {"domain": "asset", "grain": "customer-date"},
    "dws_cust_fin_d": {"domain": "cash_flow", "grain": "customer-date-source"},
}

SENSITIVE_COLUMNS = {("ads_cust_info_d", "name")}
IDENTIFIER_COLUMNS = {"pty_id", "sor_pty_id", "prdt_id", "org_id", "code"}
DATE_COLUMNS = {"data_dt", "birth_dt"}
METRIC_COLUMNS = {
    "cash_in",
    "cash_out",
    "tran_in",
    "tran_out",
    "assign_in",
    "assign_out",
    "hold_cnt",
    "mkt_val",
    "buy_cnt",
    "buy_mnt",
    "buy_rake",
    "buy_amt",
    "buy_fare",
    "sell_cnt",
    "sell_mnt",
    "sell_rake",
    "sell_amt",
    "sell_fare",
    "nm_tot_aset",
    "nm_bal",
    "fc_pur_aset",
    "fc_bal",
}

JOIN_RELATIONSHIPS = [
    (
        "ads_cust_info_d",
        "pty_id",
        "dws_cust_aset_d",
        "pty_id",
        "one_to_many",
        "客户与资产日汇总按客户号关联",
    ),
    (
        "ads_cust_info_d",
        "pty_id",
        "dws_cust_fin_d",
        "pty_id",
        "one_to_many",
        "客户与资金流动日事实按客户号关联",
    ),
    (
        "ads_cust_info_d",
        "pty_id",
        "dwd_cust_hold_d",
        "pty_id",
        "one_to_many",
        "客户与持仓日事实按客户号关联",
    ),
    (
        "ads_cust_info_d",
        "pty_id",
        "dwd_cust_tran_d",
        "pty_id",
        "one_to_many",
        "客户与交易日事实按客户号关联",
    ),
    ("ads_cust_info_d", "org_id", "dim_branch", "org_id", "many_to_one", "客户所属营业部关联"),
    ("dwd_cust_hold_d", "prdt_id", "dim_product", "prdt_id", "many_to_one", "持仓产品关联"),
    ("dwd_cust_tran_d", "prdt_id", "dim_product", "prdt_id", "many_to_one", "交易产品关联"),
    (
        "ads_cust_info_d",
        "cust_lvl_cd",
        "dim_public",
        "code",
        "many_to_one",
        "客户等级需限定 dim_public.code_type_id='100'",
    ),
    (
        "ads_cust_info_d",
        "gender_cd",
        "dim_public",
        "code",
        "many_to_one",
        "性别需限定 dim_public.code_type_id='500'",
    ),
    (
        "ads_cust_info_d",
        "edu_cd",
        "dim_public",
        "code",
        "many_to_one",
        "学历需限定 dim_public.code_type_id='600'",
    ),
]

METRICS = [
    (
        "customer_count",
        "客户数量",
        "满足筛选条件的去重客户数",
        "count(distinct ads_cust_info_d.pty_id)",
        "count",
        "customer",
        ["ads_cust_info_d"],
    ),
    (
        "total_asset",
        "客户总资产",
        "普通账户总资产与信用账户净资产之和",
        "sum(coalesce(dws_cust_aset_d.nm_tot_aset, 0) + coalesce(dws_cust_aset_d.fc_pur_aset, 0))",
        "sum",
        "customer-date",
        ["dws_cust_aset_d"],
    ),
    (
        "average_total_asset",
        "客户平均总资产",
        "指定客户范围内每位客户总资产的平均值",
        "avg(coalesce(dws_cust_aset_d.nm_tot_aset, 0) + coalesce(dws_cust_aset_d.fc_pur_aset, 0))",
        "avg",
        "customer-date",
        ["dws_cust_aset_d"],
    ),
    (
        "cash_asset",
        "客户现金资产",
        "普通账户现金资产与信用账户现金资产之和",
        "sum(coalesce(dws_cust_aset_d.nm_bal, 0) + coalesce(dws_cust_aset_d.fc_bal, 0))",
        "sum",
        "customer-date",
        ["dws_cust_aset_d"],
    ),
    (
        "daily_average_asset",
        "日均资产",
        "指定期间内客户每日总资产之和除以该期间自然日天数；官方 2026 年 Q1 口径固定除以 90。",
        "sum(coalesce(dws_cust_aset_d.nm_tot_aset, 0) + coalesce(dws_cust_aset_d.fc_pur_aset, 0)) / (to_date(end_date, 'YYYYMMDD') - to_date(start_date, 'YYYYMMDD') + 1)",
        "custom",
        "customer-period",
        ["dws_cust_aset_d"],
    ),
    (
        "holding_market_value",
        "持仓市值",
        "客户产品持仓市值",
        "sum(dwd_cust_hold_d.mkt_val)",
        "sum",
        "customer-product-date",
        ["dwd_cust_hold_d"],
    ),
    (
        "holding_quantity",
        "持有份额",
        "客户产品持有份额",
        "sum(dwd_cust_hold_d.hold_cnt)",
        "sum",
        "customer-product-date",
        ["dwd_cust_hold_d"],
    ),
    (
        "buy_amount",
        "买入金额",
        "客户买入金额",
        "sum(dwd_cust_tran_d.buy_amt)",
        "sum",
        "customer-product-date",
        ["dwd_cust_tran_d"],
    ),
    (
        "sell_amount",
        "卖出金额",
        "客户卖出金额",
        "sum(dwd_cust_tran_d.sell_amt)",
        "sum",
        "customer-product-date",
        ["dwd_cust_tran_d"],
    ),
    (
        "trade_amount",
        "交易金额",
        "买入金额与卖出金额之和",
        "sum(dwd_cust_tran_d.buy_amt) + sum(dwd_cust_tran_d.sell_amt)",
        "sum",
        "customer-product-date",
        ["dwd_cust_tran_d"],
    ),
    (
        "net_cash_flow",
        "净资金流入",
        "现金、证券和指定转入减去对应转出",
        "sum(cash_in + tran_in + assign_in - cash_out - tran_out - assign_out)",
        "sum",
        "customer-date-source",
        ["dws_cust_fin_d"],
    ),
    (
        "profit_loss",
        "资产盈亏",
        "官方 Q1 参考口径：期末普通资产+期末信用资产-期初普通资产+期初信用资产+期间资产流出-期间资产流入；输出时保留期初资产、期末资产、流入、流出和盈亏。",
        "end_nm_tot_aset + end_fc_pur_aset - begin_nm_tot_aset + begin_fc_pur_aset + period_asset_out - period_asset_in",
        "custom",
        "customer-period",
        ["dws_cust_aset_d", "dws_cust_fin_d"],
    ),
]

TERMS = [
    ("普通账户", "sys_source='nm'，表示普通账户数据。", ["普通", "普通资金账户"], False),
    ("信用账户", "sys_source='fc'，表示信用账户数据。", ["信用", "融资融券账户"], False),
    ("2026年第一季度", "日期范围为 20260101 至 20260331。", ["26年Q1", "Q1", "一季度"], False),
    (
        "交易量",
        "官方赛题中“交易量”默认按买入金额与卖出金额之和计算；只有明确要求“数量/份额”时才使用 buy_mnt 与 sell_mnt。",
        ["交易金额", "成交金额"],
        False,
    ),
    (
        "资产",
        "默认按最新数据日期统计普通账户总资产与信用账户净资产之和。",
        ["总资产", "客户资产"],
        False,
    ),
    (
        "钻石卡客户",
        "客户等级代码需要关联 dim_public 且限定 code_type_id='100'，以字典描述为准。",
        ["紫金理财钻石卡客户"],
        False,
    ),
    (
        "日均资产",
        "指定日期区间内每日总资产之和除以该区间自然日天数；2026 年 Q1 为 90 天。",
        ["平均资产", "日平均资产"],
        False,
    ),
    (
        "资产盈亏",
        "官方 Q1 参考口径为：期末普通资产+期末信用资产-期初普通资产+期初信用资产+期间资产流出-期间资产流入。期初日为 20260101，期末日为 20260331。",
        ["盈亏", "盈利情况", "资产收益"],
        False,
    ),
    ("股票交易", "股票产品大类在 dim_product.up_prdt_type_id='PT040000'。", ["股票类交易"], False),
    ("科创板", "产品小类以 dim_product.prdt_type_name='科创板' 筛选。", ["科创板股票"], False),
    (
        "不同客户年龄段资产分布",
        "官方参考口径：客户年龄分段使用 ads_cust_info_d.data_dt='20260531'，资产汇总使用 dws_cust_aset_d.data_dt='20260331'。",
        ["年龄段资产分布", "客户年龄资产分布"],
        False,
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load the official competition dataset.")
    parser.add_argument(
        "--data-dir", type=Path, required=True, help="Extracted official dataset directory"
    )
    return parser.parse_args()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Unable to decode {path.name} as UTF-8 or GB18030.")


def _official_file(data_dir: Path, pattern: str) -> Path:
    matches = sorted(data_dir.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"Expected one file matching {pattern}, found {len(matches)}.")
    return matches[0]


def _comments(data_dir: Path) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    source = _read_text(data_dir / "表描述.sql")
    table_comments = dict(
        re.findall(r"COMMENT ON TABLE\s+(\w+)\s+IS\s+'([^']*)';", source, flags=re.IGNORECASE)
    )
    column_comments = {
        (table_name, column_name): comment
        for table_name, column_name, comment in re.findall(
            r"COMMENT ON COLUMN\s+(\w+)\.(\w+)\s+IS\s+'([^']*)';",
            source,
            flags=re.IGNORECASE,
        )
    }
    return table_comments, column_comments


def _semantic_type(column_name: str, data_type: str) -> str:
    if column_name in IDENTIFIER_COLUMNS:
        return "identifier"
    if column_name in DATE_COLUMNS or data_type == "date":
        return "date"
    if column_name in METRIC_COLUMNS:
        return "amount_or_count"
    return "category"


def _is_dimension(column_name: str) -> bool:
    return column_name not in METRIC_COLUMNS


def _qualify_sql(sql: str) -> str:
    result = sql
    for table_name in sorted(OFFICIAL_TABLES, key=len, reverse=True):
        result = re.sub(
            rf"(?<![\w.]){re.escape(table_name)}(?![\w.])",
            f"mart.{table_name}",
            result,
        )
    return result.strip()


def _difficulty(case_no: int) -> str:
    if case_no == 1:
        return "simple"
    if case_no in {2, 4}:
        return "medium"
    return "complex"


def _result_payload(cursor: Any, sql: str) -> dict[str, Any]:
    cursor.execute(sql)
    columns = [item.name for item in cursor.description]
    rows = [
        {column: _jsonable(value) for column, value in zip(columns, row, strict=True)}
        for row in cursor.fetchall()
    ]
    return {"columns": columns, "rows": rows, "row_count": len(rows), "comparison": "unordered"}


def _truncate(cursor: Any) -> None:
    cursor.execute(
        "truncate table evaluation.review_decisions, evaluation.review_items, evaluation.review_batches, evaluation.eval_results, evaluation.eval_runs, evaluation.eval_cases restart identity cascade"
    )
    cursor.execute(
        "truncate table agent.result_validation_logs, agent.sql_execution_logs, agent.llm_call_logs, agent.stage_logs, agent.guardrail_events, agent.query_events, agent.query_steps, agent.query_exports, agent.query_runs restart identity cascade"
    )
    cursor.execute(
        "truncate table metadata.question_examples, metadata.rule_constraints, metadata.join_relationships, metadata.business_terms, metadata.metric_metadata, metadata.column_metadata, metadata.table_metadata restart identity cascade"
    )
    for table_name in OFFICIAL_TABLES:
        cursor.execute(f"truncate table mart.{table_name}")


def _copy_csv(cursor: Any, table_name: str, source: Path) -> int:
    with cursor.copy(
        f"copy mart.{table_name} from stdin with (format csv, header true, encoding 'UTF8')"
    ) as copy:
        with source.open("r", encoding="utf-8-sig", newline="") as file:
            while chunk := file.read(1024 * 1024):
                copy.write(chunk)
    cursor.execute(f"select count(*) from mart.{table_name}")
    return int(cursor.fetchone()[0])


def _load_metadata(cursor: Any, data_dir: Path) -> None:
    table_comments, column_comments = _comments(data_dir)
    cursor.execute(
        """
        select table_name, column_name, data_type
        from information_schema.columns
        where table_schema = 'mart'
        order by table_name, ordinal_position
        """
    )
    columns = cursor.fetchall()

    for table_name, detail in TABLE_DETAILS.items():
        cursor.execute(
            """
            insert into metadata.table_metadata
                (schema_name, table_name, display_name, domain, description, grain, refresh_frequency)
            values ('mart', %s, %s, %s, %s, %s, 'official_snapshot')
            """,
            (
                table_name,
                table_comments.get(table_name, table_name),
                detail["domain"],
                table_comments.get(table_name, "官方赛题数据表"),
                detail["grain"],
            ),
        )

    for table_name, column_name, data_type in columns:
        is_sensitive = (table_name, column_name) in SENSITIVE_COLUMNS
        cursor.execute(
            """
            insert into metadata.column_metadata
                (schema_name, table_name, column_name, display_name, data_type, description,
                 semantic_type, is_dimension, is_metric_source, is_sensitive)
            values ('mart', %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                table_name,
                column_name,
                column_comments.get((table_name, column_name), column_name),
                data_type,
                column_comments.get((table_name, column_name), "官方赛题字段"),
                _semantic_type(column_name, data_type),
                _is_dimension(column_name) and not is_sensitive,
                column_name in METRIC_COLUMNS,
                is_sensitive,
            ),
        )

    for code, name, description, formula, aggregation, grain, source_tables in METRICS:
        cursor.execute(
            """
            insert into metadata.metric_metadata
                (metric_code, metric_name, description, formula, default_aggregation, grain,
                 source_tables, owner)
            values (%s, %s, %s, %s, %s, %s, %s, 'official_dataset')
            """,
            (code, name, description, formula, aggregation, grain, Jsonb(source_tables)),
        )

    for term, definition, synonyms, clarification_required in TERMS:
        cursor.execute(
            """
            insert into metadata.business_terms
                (term, definition, synonyms, default_plan_fragment, clarification_required)
            values (%s, %s, %s, '{}'::jsonb, %s)
            """,
            (term, definition, Jsonb(synonyms), clarification_required),
        )

    for (
        left_table,
        left_column,
        right_table,
        right_column,
        relation,
        description,
    ) in JOIN_RELATIONSHIPS:
        cursor.execute(
            """
            insert into metadata.join_relationships
                (left_schema, left_table, left_column, right_schema, right_table, right_column,
                 relationship_type, description)
            values ('mart', %s, %s, 'mart', %s, %s, %s, %s)
            """,
            (left_table, left_column, right_table, right_column, relation, description),
        )

    cursor.execute(
        """
        insert into metadata.rule_constraints (rule_code, rule_name, rule_type, config, description)
        values
            ('official_tables_only', '仅使用官方赛题业务表', 'sql_scope',
             %s, 'SQL 仅可访问 mart schema 下的官方数据表。'),
            ('customer_name_masked', '客户姓名不允许返回', 'sensitive_column',
             %s, 'ads_cust_info_d.name 为脱敏姓名，仍不得在结果中返回。')
        """,
        (
            Jsonb({"schema": "mart", "tables": list(OFFICIAL_TABLES)}),
            Jsonb({"table": "ads_cust_info_d", "column": "name"}),
        ),
    )


def _load_qa_cases(cursor: Any, workbook_path: Path) -> int:
    workbook = load_workbook(workbook_path, read_only=True, data_only=False)
    sheet = workbook.active
    cases = 0
    for case_no, question, source_sql in sheet.iter_rows(min_row=2, values_only=True):
        if (
            not isinstance(case_no, int)
            or not isinstance(question, str)
            or not isinstance(source_sql, str)
        ):
            raise ValueError("Q&A.xlsx must contain integer 序号, 问题, SQL columns.")
        sql = _qualify_sql(source_sql)
        expected_result = _result_payload(cursor, sql)
        difficulty = _difficulty(case_no)
        tags = ["official", difficulty, "qa", f"qa-{case_no:03d}"]
        expected_plan = {"intent": "metric_query", "scenario": "customer_marketing"}
        cursor.execute(
            """
            insert into metadata.question_examples
                (question, difficulty, scenario, expected_query_plan, expected_sql, expected_result, tags)
            values (%s, %s, 'customer_marketing', %s, %s, %s, %s)
            """,
            (
                question.strip(),
                difficulty,
                Jsonb(expected_plan),
                sql,
                Jsonb(expected_result),
                Jsonb(tags),
            ),
        )
        cursor.execute(
            """
            insert into evaluation.eval_cases
                (case_code, question, difficulty, scenario, expected_query_plan, expected_sql,
                 expected_result, scoring_config, dataset_version, source_type, expected_status, tags)
            values (%s, %s, %s, 'customer_marketing', %s, %s, %s, %s,
                    %s, %s, 'completed', %s)
            """,
            (
                f"OFFICIAL-{case_no:03d}",
                question.strip(),
                difficulty,
                Jsonb(expected_plan),
                sql,
                Jsonb(expected_result),
                Jsonb({"comparison": "unordered", "require_execution": True}),
                DATASET_VERSION,
                SOURCE_TYPE,
                Jsonb(tags),
            ),
        )
        cases += 1
    return cases


def _analyze(cursor: Any) -> None:
    for table_name in OFFICIAL_TABLES:
        cursor.execute(f"analyze mart.{table_name}")


def main() -> None:
    args = parse_args()
    data_dir = args.data_dir.resolve()
    if not data_dir.is_dir():
        raise ValueError(f"Dataset directory does not exist: {data_dir}")
    if not (data_dir / "表描述.sql").is_file() or not (data_dir / "Q&A.xlsx").is_file():
        raise ValueError("Dataset directory must contain 表描述.sql and Q&A.xlsx.")

    raw_connection = engine.raw_connection()
    counts: dict[str, int] = {}
    try:
        with raw_connection.cursor() as cursor:
            _truncate(cursor)
            for table_name, pattern in OFFICIAL_TABLES.items():
                counts[table_name] = _copy_csv(
                    cursor, table_name, _official_file(data_dir, pattern)
                )
            _load_metadata(cursor, data_dir)
            qa_cases = _load_qa_cases(cursor, data_dir / "Q&A.xlsx")
            raw_connection.commit()
        with raw_connection.cursor() as cursor:
            _analyze(cursor)
        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        raw_connection.close()

    print(
        json.dumps(
            {
                "dataset_version": DATASET_VERSION,
                "source_type": SOURCE_TYPE,
                "table_rows": counts,
                "qa_cases": qa_cases,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
