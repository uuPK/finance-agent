from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.schemas.query_plan import QueryPlan

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}")

_ALIASES: dict[str, tuple[str, ...]] = {
    "客户": ("客户", "ads_cust_info_d", "pty_id"),
    "客户列表": ("客户列表", "ads_cust_info_d", "pty_id"),
    "客户数量": ("customer_count", "客户数量", "客户数"),
    "客户数": ("customer_count", "客户数量", "客户数"),
    "数量": ("customer_count", "客户数量", "总数"),
    "人数": ("customer_count", "客户数量", "人数"),
    "总数": ("customer_count", "total_count", "总数"),
    "多少": ("customer_count", "客户数量", "总数"),
    "几个": ("customer_count", "客户数量", "总数"),
    "几位": ("customer_count", "客户数量", "总数"),
    "资产": ("total_asset", "dws_cust_aset_d", "nm_tot_aset", "fc_pur_aset", "资产"),
    "当前资产": ("total_asset", "dws_cust_aset_d", "当前资产"),
    "总资产": ("total_asset", "dws_cust_aset_d", "总资产"),
    "平均总资产": (
        "average_total_asset",
        "dws_cust_aset_d",
        "nm_tot_aset",
        "fc_pur_aset",
        "平均总资产",
    ),
    "平均资产": (
        "average_total_asset",
        "dws_cust_aset_d",
        "nm_tot_aset",
        "fc_pur_aset",
        "平均资产",
    ),
    "日均资产": ("daily_average_asset", "dws_cust_aset_d", "日均资产", "平均资产"),
    "持仓": ("holding_market_value", "dwd_cust_hold_d", "mkt_val", "持仓"),
    "交易": ("trade_amount", "dwd_cust_tran_d", "交易"),
    "交易量": ("trade_amount", "dwd_cust_tran_d", "buy_amt", "sell_amt", "交易量"),
    "交易金额": ("trade_amount", "dwd_cust_tran_d", "buy_amt", "sell_amt", "交易金额"),
    "交易次数": ("dwd_cust_tran_d", "buy_cnt", "sell_cnt", "交易次数"),
    "产品": ("dim_product", "prdt_id", "prdt_type_name", "产品"),
    "营业部": ("dim_branch", "org_id", "org_name", "营业部"),
    "分支机构": ("dim_branch", "org_id", "org_name", "分支机构"),
    "净流入": ("net_cash_flow", "dws_cust_fin_d", "cash_in", "cash_out", "净流入"),
    "流入": ("net_cash_flow", "dws_cust_fin_d", "cash_in", "tran_in", "流入"),
    "盈亏": ("profit_loss", "dws_cust_aset_d", "dws_cust_fin_d", "资产盈亏"),
    "盈利": ("profit_loss", "dws_cust_aset_d", "dws_cust_fin_d", "资产盈亏"),
    "账户来源": ("dwd_cust_tran_d", "dws_cust_fin_d", "sys_source", "账户来源"),
    "账户类型": ("dwd_cust_tran_d", "dws_cust_fin_d", "sys_source", "账户类型"),
    "币种": ("dwd_cust_tran_d", "dwd_cust_hold_d", "ccy", "币种"),
    "交易日": ("dwd_cust_tran_d", "data_dt", "交易日"),
    "科创板": ("dim_product", "prdt_type_name", "科创板"),
    "股票": ("dim_product", "up_prdt_type_id", "PT040000", "股票"),
    "钻石卡": ("ads_cust_info_d", "dim_public", "cust_lvl_cd", "钻石卡客户"),
    "学历": ("ads_cust_info_d", "edu_cd", "dim_public", "学历"),
    "性别": ("ads_cust_info_d", "gender_cd", "dim_public", "性别"),
}

_GENERIC_KEYWORDS = {
    "customer",
    "客户",
    "客户列表",
    "pty_id",
    "查询",
    "列表",
}
_GENERIC_TOKEN_PARTS = {"cust", "pty", "id", "info"}

_TABLE_HINTS = {
    "ads_cust_info_d",
    "dim_branch",
    "dim_product",
    "dim_public",
    "dwd_cust_hold_d",
    "dwd_cust_tran_d",
    "dws_cust_aset_d",
    "dws_cust_fin_d",
}

_METRIC_TABLES: dict[str, tuple[str, ...]] = {
    "customer_count": ("ads_cust_info_d",),
    "total_asset": ("dws_cust_aset_d", "ads_cust_info_d"),
    "average_total_asset": ("dws_cust_aset_d", "ads_cust_info_d"),
    "cash_asset": ("dws_cust_aset_d", "ads_cust_info_d"),
    "daily_average_asset": ("dws_cust_aset_d", "ads_cust_info_d"),
    "holding_market_value": ("dwd_cust_hold_d", "dim_product", "ads_cust_info_d"),
    "holding_quantity": ("dwd_cust_hold_d", "dim_product", "ads_cust_info_d"),
    "trade_amount": ("dwd_cust_tran_d", "dim_product", "ads_cust_info_d"),
    "net_cash_flow": ("dws_cust_fin_d", "ads_cust_info_d"),
    "profit_loss": ("dws_cust_aset_d", "dws_cust_fin_d", "ads_cust_info_d"),
}

_GRAIN_TABLES: dict[str, tuple[str, ...]] = {
    "customer": ("ads_cust_info_d",),
    "product": ("dim_product",),
    "organization": ("dim_branch", "ads_cust_info_d"),
}


@dataclass(slots=True)
class MetadataRetrievalResult:
    """Structured metadata evidence selected for one user question."""

    keywords: list[str]
    table_names: list[str]
    metric_codes: list[str]
    business_terms: list[str]
    matched_tables: list[dict[str, Any]] = field(default_factory=list)
    matched_columns: list[dict[str, Any]] = field(default_factory=list)
    matched_metrics: list[dict[str, Any]] = field(default_factory=list)
    matched_business_terms: list[dict[str, Any]] = field(default_factory=list)
    matched_join_relationships: list[dict[str, Any]] = field(default_factory=list)
    matched_question_examples: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0

    def to_context(self) -> dict[str, Any]:
        return {
            "strategy": "structured_keyword_retrieval",
            "keywords": self.keywords,
            "table_names": self.table_names,
            "metric_codes": self.metric_codes,
            "business_terms": self.business_terms,
            "confidence": self.confidence,
            "matched_tables": self.matched_tables,
            "matched_metrics": self.matched_metrics,
            "matched_business_terms": self.matched_business_terms,
            "matched_columns": self.matched_columns,
            "matched_join_relationships": self.matched_join_relationships,
            "matched_question_examples": self.matched_question_examples,
        }


class MetadataRetriever:
    """Retrieve relevant business metadata without requiring a vector database."""

    def __init__(
        self,
        connection: Connection,
        max_tables: int = 8,
        max_metrics: int = 6,
        max_terms: int = 6,
        max_columns: int = 48,
        max_examples: int = 3,
    ) -> None:
        self.connection = connection
        self.max_tables = max_tables
        self.max_metrics = max_metrics
        self.max_terms = max_terms
        self.max_columns = max_columns
        self.max_examples = max_examples

    def retrieve(
        self, question: str | None = None, query_plan: QueryPlan | None = None
    ) -> MetadataRetrievalResult:
        keywords = self._extract_keywords(question, query_plan)
        tables = self._load_rows(
            """
            select schema_name, table_name, display_name, domain, description, grain
            from metadata.table_metadata
            where is_active = true
            """
        )
        columns = self._load_rows(
            """
            select
                schema_name,
                table_name,
                column_name,
                display_name,
                description,
                semantic_type,
                is_dimension,
                is_metric_source,
                is_sensitive
            from metadata.column_metadata
            where is_active = true
            """
        )
        metrics = self._load_rows(
            """
            select
                metric_code,
                metric_name,
                description,
                formula,
                default_aggregation,
                grain,
                source_tables,
                required_filters
            from metadata.metric_metadata
            where is_active = true
            """
        )
        terms = self._load_rows(
            """
            select term, definition, synonyms, default_plan_fragment, clarification_required
            from metadata.business_terms
            where is_active = true
            """
        )
        joins = self._load_rows(
            """
            select
                left_schema,
                left_table,
                left_column,
                right_schema,
                right_table,
                right_column,
                relationship_type,
                description
            from metadata.join_relationships
            where is_active = true
            """
        )
        examples = self._load_rows(
            """
            select question, difficulty, expected_sql, tags
            from metadata.question_examples
            where is_active = true
            """
        )

        scored_tables = self._top_scored(
            tables,
            keywords,
            fields=("table_name", "display_name", "domain", "description", "grain"),
            identity_fields=("table_name",),
            limit=self.max_tables,
        )
        scored_metrics = self._top_scored(
            metrics,
            keywords,
            fields=(
                "metric_code",
                "metric_name",
                "description",
                "formula",
                "grain",
                "source_tables",
            ),
            identity_fields=("metric_code",),
            limit=self.max_metrics,
        )
        metric_codes = self._select_metric_codes(scored_metrics)
        scored_terms = self._top_scored(
            terms,
            keywords,
            fields=("term", "definition", "synonyms", "default_plan_fragment"),
            identity_fields=("term",),
            limit=self.max_terms,
        )
        business_terms = self._select_business_terms(scored_terms)
        table_names = self._select_table_names(
            keywords=keywords,
            query_plan=query_plan,
            scored_tables=scored_tables,
            scored_metrics=scored_metrics,
            selected_metric_codes=set(metric_codes),
            scored_terms=scored_terms,
            selected_terms=set(business_terms),
            available_tables={str(row.get("table_name")) for row in tables},
        )
        scored_columns = self._top_scored(
            [row for row in columns if str(row.get("table_name", "")) in table_names],
            keywords,
            fields=(
                "table_name",
                "column_name",
                "display_name",
                "description",
                "semantic_type",
            ),
            identity_fields=("column_name",),
            limit=self.max_columns,
            keep_zero=True,
        )
        matched_joins = self._select_join_relationships(joins, set(table_names))
        scored_examples = self._top_scored(
            examples,
            keywords,
            fields=("question", "difficulty", "expected_sql", "tags"),
            identity_fields=("question",),
            limit=self.max_examples,
        )

        confidence = self._confidence(
            table_names=table_names,
            metric_codes=metric_codes,
            scored_tables=scored_tables,
            scored_metrics=scored_metrics,
            scored_terms=scored_terms,
        )

        return MetadataRetrievalResult(
            keywords=keywords[:40],
            table_names=table_names,
            metric_codes=metric_codes,
            business_terms=business_terms,
            matched_tables=self._strip_scores(scored_tables),
            matched_columns=self._strip_scores(scored_columns),
            matched_metrics=self._strip_scores(scored_metrics),
            matched_business_terms=self._strip_scores(scored_terms),
            matched_join_relationships=matched_joins,
            matched_question_examples=self._strip_scores(scored_examples),
            confidence=confidence,
        )

    def _load_rows(self, sql: str) -> list[dict[str, Any]]:
        try:
            rows = self.connection.execute(text(sql)).mappings()
            return [dict(row) for row in rows]
        except Exception:
            return []

    def _extract_keywords(self, question: str | None, query_plan: QueryPlan | None) -> list[str]:
        keywords: list[str] = []
        if question:
            keywords.extend(self._tokens(question))
            lowered_question = question.lower()
            for key, aliases in _ALIASES.items():
                if key.lower() in lowered_question:
                    keywords.extend(aliases)

        if query_plan is not None:
            payload = query_plan.model_dump(mode="json", exclude_none=True)
            keywords.extend(self._strings_from_payload(payload))
            grain = getattr(query_plan.grain, "level", None)
            if isinstance(grain, str):
                keywords.extend(_GRAIN_TABLES.get(grain, ()))

        unique: list[str] = []
        seen: set[str] = set()
        for item in keywords:
            normalized = str(item).strip().lower()
            if len(normalized) < 2 or normalized in seen:
                continue
            seen.add(normalized)
            unique.append(normalized)
        return unique

    def _tokens(self, value: str) -> list[str]:
        tokens = [match.group(0).lower() for match in _TOKEN_RE.finditer(value)]
        if value.strip():
            tokens.append(value.strip().lower())
        return tokens

    def _strings_from_payload(self, payload: Any) -> list[str]:
        if isinstance(payload, dict):
            return [
                item for value in payload.values() for item in self._strings_from_payload(value)
            ]
        if isinstance(payload, list):
            return [item for value in payload for item in self._strings_from_payload(value)]
        if isinstance(payload, str):
            return self._tokens(payload)
        if isinstance(payload, (int, float)):
            return [str(payload)]
        return []

    def _top_scored(
        self,
        rows: list[dict[str, Any]],
        keywords: list[str],
        fields: tuple[str, ...],
        identity_fields: tuple[str, ...],
        limit: int,
        keep_zero: bool = False,
    ) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        for row in rows:
            score, reasons = self._score_row(row, keywords, fields, identity_fields)
            if score > 0 or keep_zero:
                scored.append({**row, "_score": score, "_match_reasons": reasons})
        scored.sort(key=lambda item: (-int(item.get("_score", 0)), str(item)))
        return scored[:limit]

    def _score_row(
        self,
        row: dict[str, Any],
        keywords: list[str],
        fields: tuple[str, ...],
        identity_fields: tuple[str, ...],
    ) -> tuple[int, list[str]]:
        score = 0
        reasons: list[str] = []
        identity_values = {
            str(row.get(field, "")).strip().lower() for field in identity_fields if row.get(field)
        }

        for keyword in keywords:
            if not keyword:
                continue
            is_generic = keyword in _GENERIC_KEYWORDS
            for identity in identity_values:
                if keyword == identity:
                    score += 35
                    reasons.append(f"exact_identity:{keyword}")
                elif not is_generic and (keyword in identity or identity in keyword):
                    score += 18
                    reasons.append(f"identity_overlap:{keyword}")

            if is_generic:
                continue

            for field_name in fields:
                field_text = self._flatten_text(row.get(field_name)).lower()
                if not field_text:
                    continue
                if keyword == field_text:
                    score += 20
                    reasons.append(f"exact:{field_name}:{keyword}")
                elif keyword in field_text:
                    score += 8
                    reasons.append(f"contains:{field_name}:{keyword}")
                elif self._has_token_overlap(keyword, field_text):
                    score += 3
                    reasons.append(f"token:{field_name}:{keyword}")

        if row.get("is_sensitive"):
            score += 1
        return score, reasons

    def _has_token_overlap(self, keyword: str, text_value: str) -> bool:
        if "_" not in keyword:
            return False
        return any(
            part and part not in _GENERIC_TOKEN_PARTS and part in text_value
            for part in keyword.split("_")
        )

    def _flatten_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, list):
            return " ".join(self._flatten_text(item) for item in value)
        if isinstance(value, dict):
            return " ".join(f"{key} {self._flatten_text(item)}" for key, item in value.items())
        try:
            return json.dumps(value, ensure_ascii=False)
        except TypeError:
            return str(value)

    def _select_table_names(
        self,
        keywords: list[str],
        query_plan: QueryPlan | None,
        scored_tables: list[dict[str, Any]],
        scored_metrics: list[dict[str, Any]],
        selected_metric_codes: set[str],
        scored_terms: list[dict[str, Any]],
        selected_terms: set[str],
        available_tables: set[str],
    ) -> list[str]:
        selected: list[str] = []

        def add(table_name: Any) -> None:
            name = str(table_name).strip()
            if not name or name in selected:
                return
            if available_tables and name not in available_tables and name not in _TABLE_HINTS:
                return
            selected.append(name)

        for row in scored_metrics:
            code = str(row.get("metric_code", ""))
            if selected_metric_codes and code not in selected_metric_codes:
                continue
            for table_name in self._json_list(row.get("source_tables")):
                add(table_name)
            for table_name in _METRIC_TABLES.get(code, ()):
                add(table_name)

        table_score_floor = self._table_score_floor(scored_tables)
        for row in scored_tables:
            if int(row.get("_score", 0)) >= table_score_floor:
                add(row.get("table_name"))

        for keyword in keywords:
            if keyword in _TABLE_HINTS:
                add(keyword)

        for row in scored_terms:
            term = row.get("term")
            if selected_terms and term not in selected_terms:
                continue
            if not selected_terms:
                continue
            fragment = row.get("default_plan_fragment")
            if isinstance(fragment, dict):
                metric_code = str(fragment.get("metric_code", ""))
                for table_name in _METRIC_TABLES.get(metric_code, ()):
                    add(table_name)

        if query_plan is not None:
            for table_name in query_plan.data_requirements.candidate_tables:
                add(table_name)
            if query_plan.grain is not None:
                for table_name in _GRAIN_TABLES.get(query_plan.grain.level, ()):
                    add(table_name)

        expanded = self._expand_table_names(selected, keywords)
        if not expanded:
            expanded = self._fallback_table_names(keywords)
        return expanded[: self.max_tables]

    def _select_metric_codes(self, scored_metrics: list[dict[str, Any]]) -> list[str]:
        selected: list[str] = []
        for row in scored_metrics:
            code = row.get("metric_code")
            if not isinstance(code, str):
                continue
            reasons = row.get("_match_reasons", [])
            if not isinstance(reasons, list):
                reasons = []
            if any(
                isinstance(reason, str)
                and (
                    reason.startswith("exact_identity:") or reason.startswith("exact:metric_code:")
                )
                for reason in reasons
            ):
                selected.append(code)
        if selected:
            return list(dict.fromkeys(selected))[: self.max_metrics]
        return [
            str(row["metric_code"])
            for row in scored_metrics[:2]
            if isinstance(row.get("metric_code"), str)
        ]

    def _select_business_terms(self, scored_terms: list[dict[str, Any]]) -> list[str]:
        selected: list[str] = []
        for row in scored_terms:
            term = row.get("term")
            if not isinstance(term, str):
                continue
            reasons = row.get("_match_reasons", [])
            if not isinstance(reasons, list):
                reasons = []
            if any(
                isinstance(reason, str)
                and (reason.startswith("exact_identity:") or reason.startswith("exact:term:"))
                for reason in reasons
            ):
                selected.append(term)
        return list(dict.fromkeys(selected))[: self.max_terms]

    def _table_score_floor(self, scored_tables: list[dict[str, Any]]) -> int:
        if not scored_tables:
            return 0
        top_score = int(scored_tables[0].get("_score", 0))
        return max(35, int(top_score * 0.55))

    def _expand_table_names(self, table_names: list[str], keywords: list[str]) -> list[str]:
        selected = list(dict.fromkeys(table_names))
        selected_set = set(selected)

        def add(name: str) -> None:
            if name not in selected_set:
                selected.append(name)
                selected_set.add(name)

        customer_fact_tables = {
            "dws_cust_aset_d",
            "dws_cust_fin_d",
            "dwd_cust_hold_d",
            "dwd_cust_tran_d",
        }
        if customer_fact_tables & selected_set:
            add("ads_cust_info_d")
        if {"dwd_cust_hold_d", "dwd_cust_tran_d"} & selected_set:
            add("dim_product")
        if "dim_branch" in selected_set:
            add("ads_cust_info_d")
        public_dimension_terms = {
            "学历",
            "性别",
            "客户等级",
            "钻石卡",
            "男性",
            "女性",
            "教育",
            "gender",
            "education",
        }
        if any(keyword in public_dimension_terms for keyword in keywords):
            add("dim_public")
            add("ads_cust_info_d")
        if any(
            keyword
            in {"product", "产品", "基金", "股票", "科创板", "比亚迪", "招商银行", "中国平安"}
            for keyword in keywords
        ):
            add("dim_product")
        if any(keyword in {"branch", "营业部", "分支机构"} for keyword in keywords):
            add("dim_branch")
            add("ads_cust_info_d")
        return selected

    def _fallback_table_names(self, keywords: list[str]) -> list[str]:
        selected = ["ads_cust_info_d"]
        if any(
            keyword in keywords
            for keyword in (
                "asset",
                "资产",
                "total_asset",
                "daily_average_asset",
                "profit_loss",
                "盈亏",
                "盈利",
            )
        ):
            selected.append("dws_cust_aset_d")
        if any(keyword in keywords for keyword in ("profit_loss", "盈亏", "盈利")):
            selected.append("dws_cust_fin_d")
        if any(keyword in keywords for keyword in ("hold", "持仓", "holding")):
            selected.extend(["dwd_cust_hold_d", "dim_product"])
        if any(keyword in keywords for keyword in ("trade", "交易", "trade_amount")):
            selected.extend(["dwd_cust_tran_d", "dim_product"])
        if any(keyword in keywords for keyword in ("net_cash_flow", "净流入", "流入")):
            selected.append("dws_cust_fin_d")
        if any(keyword in keywords for keyword in ("branch", "营业部", "分支机构")):
            selected.append("dim_branch")
        return list(dict.fromkeys(selected))

    def _select_join_relationships(
        self, rows: list[dict[str, Any]], table_names: set[str]
    ) -> list[dict[str, Any]]:
        matched: list[dict[str, Any]] = []
        for row in rows:
            left = str(row.get("left_table", ""))
            right = str(row.get("right_table", ""))
            if left in table_names and right in table_names:
                matched.append(row)
        return matched

    def _json_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value]
        if isinstance(value, str):
            try:
                loaded = json.loads(value)
            except json.JSONDecodeError:
                return [value]
            if isinstance(loaded, list):
                return [str(item) for item in loaded]
        return []

    def _confidence(
        self,
        table_names: list[str],
        metric_codes: list[str],
        scored_tables: list[dict[str, Any]],
        scored_metrics: list[dict[str, Any]],
        scored_terms: list[dict[str, Any]],
    ) -> float:
        best_score = max(
            [
                int(item.get("_score", 0))
                for item in [*scored_tables, *scored_metrics, *scored_terms]
            ]
            or [0]
        )
        score = 0.25
        if table_names:
            score += 0.2
        if metric_codes:
            score += 0.2
        if best_score >= 50:
            score += 0.25
        elif best_score >= 20:
            score += 0.15
        return round(min(score, 0.95), 2)

    def _strip_scores(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        stripped = []
        for row in rows:
            item = dict(row)
            item["score"] = item.pop("_score", 0)
            reasons = item.pop("_match_reasons", [])
            item["match_reasons"] = reasons[:8] if isinstance(reasons, list) else []
            stripped.append(item)
        return stripped
