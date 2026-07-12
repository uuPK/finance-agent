import re

from app.schemas.query_plan import (
    BusinessEntity,
    ClarificationQuestion,
    DataRequirement,
    MetadataReference,
    PlanAssumption,
    QueryDimension,
    QueryFilter,
    QueryGrain,
    QueryMetric,
    QueryOutput,
    QueryPlan,
    QueryValue,
    SafetyRequirement,
    TimeRange,
)


class RuleBasedQueryPlanActor:
    """Offline QueryPlan actor used before the LLM implementation is wired in."""

    COUNT_INTENT_TOKENS = ("数量", "人数", "多少", "总数", "几个", "几位", "count")

    def build(self, question: str) -> QueryPlan:
        normalized = question.strip()
        lower_question = normalized.lower()

        clarifications = self._detect_clarifications(normalized)
        time_range = self._detect_time_range(normalized)
        metrics = self._detect_metrics(normalized, time_range)
        filters = self._detect_filters(normalized, time_range)
        dimensions = self._detect_dimensions(normalized)
        subject = self._detect_subject(normalized)
        grain = self._detect_grain(normalized)
        intent = self._detect_intent(normalized, lower_question)

        plan_status = "needs_clarification" if clarifications else "ready"

        return QueryPlan(
            plan_status=plan_status,
            intent=intent,
            scenario="customer_marketing",
            question=question,
            subject=subject,
            entities=[subject] if subject else [],
            metrics=metrics,
            dimensions=dimensions,
            filters=filters,
            time_range=time_range,
            grain=grain,
            data_requirements=self._build_data_requirements(metrics, filters),
            output=self._build_output(normalized, grain),
            safety=SafetyRequirement(),
            clarifications=clarifications,
            assumptions=self._detect_assumptions(normalized, clarifications),
            confidence=0.72 if clarifications else 0.82,
        )

    def _detect_intent(self, question: str, lower_question: str) -> str:
        if any(token in question for token in ["趋势", "变化", "走势"]):
            return "trend_analysis"
        if any(token in question for token in ["排名", "top", "Top", "最高", "最多"]):
            return "ranking_query"
        if any(token in question for token in ["效果", "转化", "触达"]):
            return "marketing_effect_analysis"
        if any(token in question for token in ["口径", "定义", "字段", "表结构", "哪张表"]):
            return "metadata_question"
        if "客户" in question and any(token in question for token in ["筛选", "找出", "列表", "名单"]):
            return "customer_segmentation"
        if any(token in question for token in self.COUNT_INTENT_TOKENS):
            return "metric_query"
        if "客户" in question:
            return "customer_segmentation"
        return "unclear"

    def _detect_subject(self, question: str) -> BusinessEntity | None:
        if "客户" in question:
            return BusinessEntity(name="客户", entity_type="customer", is_resolved=True)
        if "服务经理" in question or "经理" in question:
            return BusinessEntity(name="服务经理", entity_type="manager", is_resolved=True)
        if "产品" in question or "基金" in question:
            return BusinessEntity(name="产品", entity_type="product", is_resolved=True)
        return None

    def _detect_metrics(self, question: str, time_range: TimeRange | None) -> list[QueryMetric]:
        metrics: list[QueryMetric] = []

        if "交易次数" in question or "交易活跃" in question or "活跃客户" in question:
            metrics.append(
                QueryMetric(
                    name="近三个月交易次数" if time_range else "交易次数",
                    metric_code="trade_count_90d" if time_range else "trade_count",
                    definition_id="metric:trade_count_90d" if time_range else None,
                    aggregation="count",
                    alias="交易次数",
                    time_window=time_range,
                    metadata_ref=self._metric_ref("trade_count_90d", "近90天交易次数")
                    if time_range
                    else None,
                    is_resolved=time_range is not None,
                    requires_clarification=time_range is None,
                )
            )

        if "资产" in question:
            metrics.append(
                QueryMetric(
                    name="当前资产",
                    metric_code="current_total_asset",
                    definition_id="metric:current_total_asset",
                    aggregation="latest",
                    alias="当前资产",
                    metadata_ref=self._metric_ref("current_total_asset", "当前资产"),
                    is_resolved=True,
                )
            )

        if "净流入" in question or "流入" in question:
            metrics.append(
                QueryMetric(
                    name="近三个月资产净流入" if time_range else "资产净流入",
                    metric_code="net_asset_inflow_90d" if time_range else "net_asset_inflow",
                    definition_id="metric:net_asset_inflow_90d" if time_range else None,
                    aggregation="sum",
                    alias="资产净流入",
                    time_window=time_range,
                    metadata_ref=self._metric_ref("net_asset_inflow_90d", "近90天资产净流入")
                    if time_range
                    else None,
                    is_resolved=time_range is not None,
                    requires_clarification=time_range is None,
                )
            )

        if "持有基金" in question or "基金持仓" in question:
            metrics.append(
                QueryMetric(
                    name="基金持仓",
                    metric_code="fund_holding_amount",
                    definition_id="metric:fund_holding_amount",
                    aggregation="latest",
                    alias="基金持仓",
                    metadata_ref=self._metric_ref("fund_holding_amount", "基金持仓金额"),
                    is_resolved=True,
                )
            )

        if any(token in question for token in self.COUNT_INTENT_TOKENS):
            metrics.append(
                QueryMetric(
                    name="客户数量",
                    metric_code="customer_count",
                    definition_id="metric:customer_count",
                    aggregation="count_distinct",
                    alias="客户数量",
                    metadata_ref=self._metric_ref("customer_count", "客户数量"),
                    is_resolved=True,
                )
            )

        return self._dedupe_metrics(metrics)

    def _detect_filters(self, question: str, time_range: TimeRange | None) -> list[QueryFilter]:
        filters: list[QueryFilter] = []

        asset_threshold = self._extract_amount_threshold(question)
        if asset_threshold is not None:
            filters.append(
                QueryFilter(
                    term="当前资产",
                    operator=">",
                    value=QueryValue(
                        raw=asset_threshold["raw"],
                        normalized=asset_threshold["value"],
                        value_type="number",
                    ),
                    metric_code="current_total_asset",
                    source="user",
                    metadata_ref=self._metric_ref("current_total_asset", "当前资产"),
                    is_resolved=True,
                )
            )

        trade_count_threshold = self._extract_trade_count_threshold(question)
        if trade_count_threshold is not None:
            filters.append(
                QueryFilter(
                    term="交易次数",
                    operator=">",
                    value=QueryValue(
                        raw=trade_count_threshold,
                        normalized=trade_count_threshold,
                        value_type="number",
                    ),
                    metric_code="trade_count_90d" if time_range else "trade_count",
                    source="user",
                    is_resolved=time_range is not None,
                    requires_clarification=time_range is None,
                )
            )

        if "未持有基金" in question or "尚未持有基金" in question or "无基金持仓" in question:
            filters.append(
                QueryFilter(
                    term="基金持仓",
                    operator="not_exists",
                    value=QueryValue(raw="未持有基金", normalized=False, value_type="boolean"),
                    metric_code="fund_holding_amount",
                    source="user",
                    metadata_ref=self._metric_ref("fund_holding_amount", "基金持仓金额"),
                    is_resolved=True,
                )
            )

        return filters

    def _detect_dimensions(self, question: str) -> list[QueryDimension]:
        dimensions: list[QueryDimension] = []
        if "客户" in question:
            dimensions.append(
                QueryDimension(
                    name="客户",
                    dimension_code="customer_id",
                    role="display",
                    alias="客户",
                    metadata_ref=MetadataReference(
                        ref_type="column", code="customer_id", name="客户ID"
                    ),
                    is_resolved=True,
                )
            )
        if "服务经理" in question or "经理" in question:
            dimensions.append(
                QueryDimension(
                    name="服务经理",
                    dimension_code="manager_id",
                    role="group_by" if self._asks_for_grouping(question) else "display",
                    alias="服务经理",
                    metadata_ref=MetadataReference(
                        ref_type="column", code="manager_id", name="服务经理ID"
                    ),
                    is_resolved=True,
                )
            )
        return dimensions

    def _detect_time_range(self, question: str) -> TimeRange | None:
        if "近三个月" in question or "最近三个月" in question:
            return TimeRange(
                label="近三个月",
                relative="last_3_months",
                granularity="day",
                is_resolved=False,
            )
        if "近90天" in question or "最近90天" in question:
            return TimeRange(
                label="近90天",
                relative="last_90_days",
                granularity="day",
                is_resolved=False,
            )
        if "近30天" in question or "最近30天" in question:
            return TimeRange(
                label="近30天",
                relative="last_30_days",
                granularity="day",
                is_resolved=False,
            )
        return None

    def _detect_grain(self, question: str) -> QueryGrain:
        if any(token in question for token in self.COUNT_INTENT_TOKENS):
            return QueryGrain(
                level="aggregate", keys=[], description="汇总级", is_resolved=True
            )
        if "服务经理" in question and self._asks_for_grouping(question):
            return QueryGrain(
                level="manager", keys=["manager_id"], description="服务经理级", is_resolved=True
            )
        return QueryGrain(
            level="customer", keys=["customer_id"], description="客户级", is_resolved=True
        )

    def _build_output(self, question: str, grain: QueryGrain) -> QueryOutput:
        if grain.level == "aggregate":
            return QueryOutput(format="summary", columns=["客户数量"], limit=100)
        columns = ["客户"]
        if "资产" in question:
            columns.append("当前资产")
        if "交易" in question or "活跃" in question:
            columns.append("交易次数")
        if "流入" in question:
            columns.append("资产净流入")
        if "基金" in question:
            columns.append("基金持仓")
        return QueryOutput(format="table", columns=columns, limit=100)

    def _build_data_requirements(
        self, metrics: list[QueryMetric], filters: list[QueryFilter]
    ) -> DataRequirement:
        domains: set[str] = {"customer"}
        candidate_tables: set[str] = {"customer_info"}

        metric_codes = {metric.metric_code for metric in metrics}
        filter_codes = {query_filter.metric_code for query_filter in filters}
        all_codes = metric_codes | filter_codes

        if {"current_total_asset", "net_asset_inflow_90d", "net_asset_inflow"} & all_codes:
            domains.add("asset")
            candidate_tables.add("customer_current_asset")
        if {"trade_count_90d", "trade_count"} & all_codes:
            domains.add("trade")
            candidate_tables.add("customer_trade_90d")
        if "fund_holding_amount" in all_codes:
            domains.add("holding")
            candidate_tables.add("customer_position_daily")

        return DataRequirement(
            domains=sorted(domains),
            candidate_tables=sorted(candidate_tables),
            required_join_paths=[],
            required_metadata_refs=[],
        )

    def _detect_clarifications(self, question: str) -> list[ClarificationQuestion]:
        clarifications: list[ClarificationQuestion] = []

        if "高净值" in question and not self._extract_amount_threshold(question):
            clarifications.append(
                ClarificationQuestion(
                    field="高净值客户",
                    question="请确认高净值客户的资产门槛。",
                    reason="不同资产门槛会改变客群筛选结果。",
                    options=["当前资产 >= 50万", "当前资产 >= 100万", "当前资产 >= 300万"],
                )
            )

        if "活跃客户" in question and not (
            "近三个月" in question or "近90天" in question or "近30天" in question
        ):
            clarifications.append(
                ClarificationQuestion(
                    field="活跃客户",
                    question="请确认活跃客户的时间窗口和口径。",
                    reason="活跃客户可以按交易次数、交易金额或登录行为定义。",
                    options=[
                        "近30天交易次数 >= 3",
                        "近90天交易次数 >= 3",
                        "近90天交易金额 >= 10000",
                    ],
                )
            )

        if all(token not in question for token in ["客户", "服务经理", "产品", "基金"]):
            clarifications.append(
                ClarificationQuestion(
                    field="查询主体",
                    question="请确认本次查询的主体。",
                    reason="当前问题无法判断是查询客户、产品还是服务经理。",
                    options=["客户", "产品", "服务经理"],
                )
            )

        return clarifications

    def _detect_assumptions(
        self, question: str, clarifications: list[ClarificationQuestion]
    ) -> list[PlanAssumption]:
        if clarifications:
            return []
        assumptions: list[PlanAssumption] = []
        if "资产" in question and "当前" not in question:
            assumptions.append(
                PlanAssumption(
                    field="资产",
                    value="当前资产",
                    reason="用户未指定资产时点，默认按当前资产理解。",
                )
            )
        return assumptions

    def _extract_amount_threshold(self, question: str) -> dict[str, int | str] | None:
        match = re.search(r"(\d+(?:\.\d+)?)\s*万", question)
        if not match:
            return None
        raw_value = match.group(0)
        return {"raw": raw_value, "value": int(float(match.group(1)) * 10000)}

    def _extract_trade_count_threshold(self, question: str) -> int | None:
        match = re.search(r"(?:交易次数)?(?:超过|大于|>)\s*(\d+)\s*次?", question)
        if match:
            return int(match.group(1))
        return None

    def _asks_for_grouping(self, question: str) -> bool:
        return any(token in question for token in ["按", "汇总"])

    def _metric_ref(self, code: str, name: str) -> MetadataReference:
        return MetadataReference(ref_type="metric", ref_id=f"metric:{code}", code=code, name=name)

    def _dedupe_metrics(self, metrics: list[QueryMetric]) -> list[QueryMetric]:
        deduped: list[QueryMetric] = []
        seen: set[str] = set()
        for metric in metrics:
            key = metric.metric_code or metric.name
            if key in seen:
                continue
            seen.add(key)
            deduped.append(metric)
        return deduped
