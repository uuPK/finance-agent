import re
from datetime import date

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

    COUNT_INTENT_TOKENS = ("数量", "人数", "多少", "总数", "几个", "几位", "统计", "分布", "count")

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

        unresolved_filters = [
            query_filter for query_filter in filters if query_filter.requires_clarification
        ]
        known_clarification_fields = {item.field for item in clarifications}
        clarifications.extend(
            ClarificationQuestion(
                field=query_filter.term,
                question=f"请明确“{query_filter.term}”的计算口径或适用时间范围。",
                reason="该过滤条件尚未解析为可执行的业务口径。",
            )
            for query_filter in unresolved_filters
            if query_filter.term not in known_clarification_fields
        )
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
            data_requirements=self._build_data_requirements(metrics, filters, dimensions),
            output=self._build_output(normalized, grain, metrics, dimensions, filters),
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
        if "客户" in question and any(
            token in question for token in ["筛选", "找出", "列表", "名单"]
        ):
            return "customer_segmentation"
        if any(token in question for token in self.COUNT_INTENT_TOKENS):
            return "metric_query"
        if "客户" in question:
            return "customer_segmentation"
        return "unclear"

    def _detect_subject(self, question: str) -> BusinessEntity | None:
        if "客户" in question:
            return BusinessEntity(name="客户", entity_type="customer", is_resolved=True)
        if "营业部" in question or "分支机构" in question:
            return BusinessEntity(name="营业部", entity_type="organization", is_resolved=True)
        if any(token in question for token in ("产品类型", "产品类别", "产品分类")):
            return BusinessEntity(name="产品", entity_type="product", is_resolved=True)
        if any(
            token in question
            for token in ("资产", "交易", "成交", "持仓", "资金流", "净流入", "币种", "账户来源")
        ):
            return BusinessEntity(name="客户", entity_type="customer", is_resolved=True)
        if "产品" in question or "基金" in question:
            return BusinessEntity(name="产品", entity_type="product", is_resolved=True)
        return None

    def _detect_metrics(self, question: str, time_range: TimeRange | None) -> list[QueryMetric]:
        metrics: list[QueryMetric] = []
        # "截至最新资产日期" names the snapshot anchor, not an asset measure.
        # Remove this date phrase before deciding whether total-asset output was asked for.
        asset_intent_question = question.replace("最新资产日期", "").replace("资产日期", "")

        if "平均交易金额" in question or "平均交易额" in question:
            metrics.append(
                QueryMetric(
                    name="平均交易金额",
                    metric_code="average_trade_amount",
                    definition_id="metric:average_trade_amount",
                    aggregation="avg",
                    alias="平均交易金额",
                    time_window=time_range,
                    metadata_ref=self._metric_ref("average_trade_amount", "平均交易金额"),
                    is_resolved=True,
                )
            )
        elif "交易费用" in question or "手续费" in question:
            metrics.append(
                QueryMetric(
                    name="交易费用",
                    metric_code="trade_fee",
                    definition_id="metric:trade_fee",
                    aggregation="sum",
                    alias="交易费用",
                    time_window=time_range,
                    metadata_ref=self._metric_ref("trade_fee", "交易费用"),
                    is_resolved=True,
                )
            )
        elif any(token in question for token in ("成交数量", "交易数量", "成交份额")):
            metrics.append(
                QueryMetric(
                    name="成交数量",
                    metric_code="trade_quantity",
                    definition_id="metric:trade_quantity",
                    aggregation="sum",
                    alias="成交数量",
                    time_window=time_range,
                    metadata_ref=self._metric_ref("trade_quantity", "成交数量"),
                    is_resolved=True,
                )
            )
        elif "买入金额" in question:
            metrics.append(
                QueryMetric(
                    name="买入金额",
                    metric_code="buy_amount",
                    definition_id="metric:buy_amount",
                    aggregation="sum",
                    alias="买入金额",
                    time_window=time_range,
                    metadata_ref=self._metric_ref("buy_amount", "买入金额"),
                    is_resolved=True,
                )
            )
        elif any(token in question for token in ("交易", "成交", "买入", "卖出")):
            metrics.append(
                QueryMetric(
                    name="交易金额",
                    metric_code="trade_amount",
                    definition_id="metric:trade_amount",
                    aggregation="sum",
                    alias="交易金额",
                    time_window=time_range,
                    metadata_ref=self._metric_ref("trade_amount", "交易金额"),
                    is_resolved=True,
                )
            )

        if "日均资产" in asset_intent_question:
            metrics.append(
                QueryMetric(
                    name="日均资产",
                    metric_code="daily_average_asset",
                    definition_id="metric:daily_average_asset",
                    aggregation="avg",
                    alias="日均资产",
                    time_window=time_range,
                    metadata_ref=self._metric_ref("daily_average_asset", "日均资产"),
                    is_resolved=True,
                )
            )
        has_average_total_asset = any(
            token in asset_intent_question for token in ("平均总资产", "平均资产")
        )
        if has_average_total_asset:
            metrics.append(
                QueryMetric(
                    name="平均总资产",
                    metric_code="average_total_asset",
                    definition_id="metric:average_total_asset",
                    aggregation="avg",
                    alias="平均总资产",
                    metadata_ref=self._metric_ref("average_total_asset", "平均总资产"),
                    is_resolved=True,
                )
            )
        if "平均年龄" in question:
            metrics.append(
                QueryMetric(
                    name="客户平均年龄",
                    metric_code="average_customer_age",
                    definition_id="metric:average_customer_age",
                    aggregation="avg",
                    alias="客户平均年龄",
                    metadata_ref=self._metric_ref("average_customer_age", "客户平均年龄"),
                    is_resolved=True,
                )
            )
        cash_asset_requested = "现金资产" in asset_intent_question
        if cash_asset_requested:
            metrics.append(
                QueryMetric(
                    name="现金资产",
                    metric_code="cash_asset",
                    definition_id="metric:cash_asset",
                    aggregation="sum",
                    alias="现金资产",
                    time_window=time_range,
                    metadata_ref=self._metric_ref("cash_asset", "现金资产"),
                    is_resolved=True,
                )
            )
        account_asset_metric: str | None = None
        if "普通账户" in asset_intent_question and "资产" in asset_intent_question:
            account_asset_metric = "normal_total_asset"
            metrics.append(
                QueryMetric(
                    name="普通账户总资产",
                    metric_code=account_asset_metric,
                    definition_id=f"metric:{account_asset_metric}",
                    aggregation="sum",
                    alias="普通账户总资产",
                    time_window=time_range,
                    metadata_ref=self._metric_ref(account_asset_metric, "普通账户总资产"),
                    is_resolved=True,
                )
            )
        elif "信用账户" in asset_intent_question and "资产" in asset_intent_question:
            account_asset_metric = "credit_total_asset"
            metrics.append(
                QueryMetric(
                    name="信用账户净资产",
                    metric_code=account_asset_metric,
                    definition_id=f"metric:{account_asset_metric}",
                    aggregation="sum",
                    alias="信用账户净资产",
                    time_window=time_range,
                    metadata_ref=self._metric_ref(account_asset_metric, "信用账户净资产"),
                    is_resolved=True,
                )
            )
        needs_total_asset = (
            "资产" in asset_intent_question
            and "日均资产" not in asset_intent_question
            and not any(token in asset_intent_question for token in ("盈亏", "盈利"))
            and account_asset_metric is None
            and not cash_asset_requested
            and (
                not has_average_total_asset
                or asset_intent_question.count("总资产")
                > asset_intent_question.count("平均总资产")
                or "总资产合计" in asset_intent_question
            )
        )
        if needs_total_asset:
            metrics.append(
                QueryMetric(
                    name="总资产",
                    metric_code="total_asset",
                    definition_id="metric:total_asset",
                    aggregation="sum",
                    alias="总资产",
                    metadata_ref=self._metric_ref("total_asset", "总资产"),
                    is_resolved=True,
                )
            )

        if "盈亏" in question or "盈利" in question:
            metrics.append(
                QueryMetric(
                    name="资产盈亏",
                    metric_code="profit_loss",
                    definition_id="metric:profit_loss",
                    aggregation="custom",
                    alias="资产盈亏",
                    time_window=time_range,
                    metadata_ref=self._metric_ref("profit_loss", "资产盈亏"),
                    is_resolved=True,
                )
            )
        elif "现金流入" in question and "现金净流入" not in question:
            metrics.append(
                QueryMetric(
                    name="现金流入金额",
                    metric_code="cash_in_amount",
                    definition_id="metric:cash_in_amount",
                    aggregation="sum",
                    alias="现金流入金额",
                    time_window=time_range,
                    metadata_ref=self._metric_ref("cash_in_amount", "现金流入金额"),
                    is_resolved=True,
                )
            )
        elif "现金净流入" in question:
            metrics.append(
                QueryMetric(
                    name="现金净流入",
                    metric_code="net_cash_inflow",
                    definition_id="metric:net_cash_inflow",
                    aggregation="sum",
                    alias="现金净流入",
                    time_window=time_range,
                    metadata_ref=self._metric_ref("net_cash_inflow", "现金净流入"),
                    is_resolved=True,
                )
            )
        elif "转账金额" in question:
            metrics.append(
                QueryMetric(
                    name="转账金额",
                    metric_code="transfer_amount",
                    definition_id="metric:transfer_amount",
                    aggregation="sum",
                    alias="转账金额",
                    time_window=time_range,
                    metadata_ref=self._metric_ref("transfer_amount", "转账金额"),
                    is_resolved=True,
                )
            )
        elif "划拨金额" in question:
            metrics.append(
                QueryMetric(
                    name="划拨金额",
                    metric_code="assignment_amount",
                    definition_id="metric:assignment_amount",
                    aggregation="sum",
                    alias="划拨金额",
                    time_window=time_range,
                    metadata_ref=self._metric_ref("assignment_amount", "划拨金额"),
                    is_resolved=True,
                )
            )
        elif any(token in question for token in ("净流入", "流入", "净流出")):
            metrics.append(
                QueryMetric(
                    name="资金净流入",
                    metric_code="net_cash_flow",
                    definition_id="metric:net_cash_flow",
                    aggregation="sum",
                    alias="资金净流入",
                    time_window=time_range,
                    metadata_ref=self._metric_ref("net_cash_flow", "资金净流入"),
                    is_resolved=True,
                )
            )

        if any(token in question for token in ("持有份额", "持仓份额", "持仓数量")):
            metrics.append(
                QueryMetric(
                    name="持有份额",
                    metric_code="holding_quantity",
                    definition_id="metric:holding_quantity",
                    aggregation="sum",
                    alias="持有份额",
                    time_window=time_range,
                    metadata_ref=self._metric_ref("holding_quantity", "持有份额"),
                    is_resolved=True,
                )
            )
        elif any(token in question for token in ("持仓", "持有", "持有产品")):
            metrics.append(
                QueryMetric(
                    name="持仓市值",
                    metric_code="holding_market_value",
                    definition_id="metric:holding_market_value",
                    aggregation="sum",
                    alias="持仓市值",
                    metadata_ref=self._metric_ref("holding_market_value", "持仓市值"),
                    is_resolved=True,
                )
            )

        explicit_count = any(
            token in question
            for token in ("数量", "人数", "多少", "总数", "几个", "几位", "客户数")
        )
        customer_count_requested = any(
            token in question
            for token in (
                "客户数",
                "客户数量",
                "去重客户",
                "几位客户",
                "多少位客户",
                "客户有多少",
                "客户多少",
            )
        )
        if (
            (explicit_count and (customer_count_requested or not metrics))
            or ("分布" in question and "客户" in question and "年龄" in question)
            or (not metrics and "统计" in question)
        ):
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

        # 买卖双向、不同产品数都是客户筛选条件；用户只问客户数时，不把交易金额
        # 或持仓市值误当成待输出指标。筛选条件会在 _detect_filters 中保留。
        if self._is_bidirectional_trade_question(question) and customer_count_requested:
            metrics = [metric for metric in metrics if metric.metric_code != "trade_amount"]
        if self._is_multi_product_holding_question(question) and customer_count_requested:
            metrics = [
                metric for metric in metrics if metric.metric_code != "holding_market_value"
            ]
        return self._dedupe_metrics(metrics)

    def _detect_filters(self, question: str, time_range: TimeRange | None) -> list[QueryFilter]:
        filters: list[QueryFilter] = []

        metric_labels = {
            "total_asset": "总资产",
            "daily_average_asset": "日均资产",
            "trade_amount": "交易金额",
            "trade_fee": "交易费用",
            "holding_market_value": "持仓市值",
            "cash_in_amount": "现金流入金额",
        }
        for threshold in self._extract_amount_thresholds(question):
            metric_code = threshold["metric_code"]
            filters.append(
                QueryFilter(
                    term=metric_labels[metric_code],
                    operator=str(threshold["operator"]),
                    value=QueryValue(
                        raw=threshold["raw"],
                        normalized=threshold["value"],
                        value_type="number",
                    ),
                    metric_code=metric_code,
                    source="user",
                    metadata_ref=self._metric_ref(metric_code, metric_labels[metric_code]),
                    is_resolved=True,
                )
            )

        age_match = re.search(r"年龄\s*(?:大于|超过|>)\s*(\d+)\s*岁?", question)
        if age_match:
            filters.append(
                QueryFilter(
                    term="客户年龄",
                    operator=">",
                    value=QueryValue(
                        raw=age_match.group(1),
                        normalized=int(age_match.group(1)),
                        value_type="number",
                    ),
                    field_code="cust_age",
                    source="user",
                    is_resolved=True,
                )
            )

        if "钻石卡" in question:
            filters.append(
                QueryFilter(
                    term="钻石卡客户",
                    operator="=",
                    value=QueryValue(raw="钻石卡客户", normalized="钻石卡客户"),
                    field_code="cust_lvl_cd",
                    source="user",
                    is_resolved=True,
                )
            )
        if "男性" in question:
            filters.append(
                QueryFilter(
                    term="性别",
                    operator="=",
                    value=QueryValue(raw="男性", normalized="男性"),
                    field_code="gender_cd",
                    source="user",
                    is_resolved=True,
                )
            )
        if "比亚迪" in question:
            filters.append(
                QueryFilter(
                    term="产品名称",
                    operator="=",
                    value=QueryValue(raw="比亚迪", normalized="比亚迪"),
                    field_code="prdt_name",
                    source="user",
                    is_resolved=True,
                )
            )
        if "科创板" in question:
            filters.append(
                QueryFilter(
                    term="产品类型",
                    operator="=",
                    value=QueryValue(raw="科创板", normalized="科创板"),
                    field_code="prdt_type_name",
                    source="user",
                    is_resolved=True,
                )
            )
        if "股票" in question and any(token in question for token in ("交易", "成交")):
            filters.append(
                QueryFilter(
                    term="股票类产品",
                    operator="=",
                    value=QueryValue(raw="PT040000", normalized="PT040000"),
                    field_code="up_prdt_type_id",
                    source="business_term",
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
                    metric_code="trade_amount",
                    source="user",
                    is_resolved=time_range is not None,
                    requires_clarification=time_range is None,
                )
            )

        if self._is_bidirectional_trade_question(question):
            filters.append(
                QueryFilter(
                    term="双向交易客户",
                    operator="exists",
                    value=QueryValue(raw=True, normalized=True, value_type="boolean"),
                    metric_code="bidirectional_trade_customer",
                    source="business_term",
                    metadata_ref=self._metric_ref(
                        "bidirectional_trade_customer", "双向交易客户"
                    ),
                    is_resolved=time_range is not None,
                    requires_clarification=time_range is None,
                )
            )

        distinct_product_threshold = self._extract_distinct_product_threshold(question)
        if (
            distinct_product_threshold is not None
            and self._is_multi_product_holding_question(question)
        ):
            filters.append(
                QueryFilter(
                    term="不同产品持有数量",
                    operator=">=",
                    value=QueryValue(
                        raw=distinct_product_threshold,
                        normalized=distinct_product_threshold,
                        value_type="number",
                    ),
                    metric_code="distinct_holding_product_count",
                    source="business_term",
                    metadata_ref=self._metric_ref(
                        "distinct_holding_product_count", "不同产品持有数量"
                    ),
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
                    metric_code="holding_market_value",
                    source="user",
                    metadata_ref=self._metric_ref("holding_market_value", "持仓市值"),
                    is_resolved=True,
                )
            )

        return filters

    def _detect_dimensions(self, question: str) -> list[QueryDimension]:
        dimensions: list[QueryDimension] = []
        if "客户" in question and any(
            token in question for token in ("列表", "名单", "明细", "找出")
        ):
            dimensions.append(
                QueryDimension(
                    name="客户",
                    dimension_code="pty_id",
                    role="display",
                    alias="客户",
                    metadata_ref=MetadataReference(
                        ref_type="column", code="pty_id", name="客户标识"
                    ),
                    is_resolved=True,
                )
            )
        if "一级营业部" in question:
            dimensions.append(
                QueryDimension(
                    name="一级营业部",
                    dimension_code="up_org_name",
                    role="group_by"
                    if self._asks_for_grouping(question) or "统计" in question or "展示" in question
                    else "display",
                    alias="一级营业部",
                    metadata_ref=MetadataReference(
                        ref_type="column", code="up_org_name", name="一级营业部名称"
                    ),
                    is_resolved=True,
                )
            )
            both_branch_levels = (
                "一级营业部、营业部",
                "一级营业部和营业部",
                "一级营业部及营业部",
            )
            if any(marker in question for marker in both_branch_levels):
                dimensions.append(
                    QueryDimension(
                        name="营业部",
                        dimension_code="org_name",
                        role="group_by",
                        alias="营业部",
                        metadata_ref=MetadataReference(
                            ref_type="column", code="org_name", name="营业部名称"
                        ),
                        is_resolved=True,
                    )
                )
        elif "营业部" in question or "分支机构" in question:
            dimensions.append(
                QueryDimension(
                    name="营业部",
                    dimension_code="org_name",
                    role=(
                        "group_by"
                        if self._asks_for_grouping(question)
                        or "分布" in question
                        or "统计" in question
                        else "display"
                    ),
                    alias="营业部",
                    metadata_ref=MetadataReference(
                        ref_type="column", code="org_name", name="营业部名称"
                    ),
                    is_resolved=True,
                )
            )
            if "分布" in question or "统计" in question:
                dimensions.append(
                    QueryDimension(
                        name="一级营业部",
                        dimension_code="up_org_name",
                        role="group_by",
                        alias="一级营业部",
                        is_resolved=True,
                    )
                )
        if "分公司" in question and not any(
            dimension.dimension_code == "up_org_name" for dimension in dimensions
        ):
            dimensions.append(
                QueryDimension(
                    name="一级营业部",
                    dimension_code="up_org_name",
                    role="group_by"
                    if self._asks_for_grouping(question) or "分布" in question
                    else "display",
                    alias="一级营业部",
                    is_resolved=True,
                )
            )
        if self._dimension_grouping_requested(question, "省份"):
            dimensions.append(
                QueryDimension(
                    name="省份",
                    dimension_code="prov_name",
                    role="group_by",
                    alias="省份",
                    is_resolved=True,
                )
            )
            if "客户省份分析统计" in question:
                dimensions.append(
                    QueryDimension(
                        name="城市",
                        dimension_code="city_name",
                        role="group_by",
                        alias="城市",
                        is_resolved=True,
                    )
                )
        if self._dimension_grouping_requested(question, "城市"):
            dimensions.append(
                QueryDimension(
                    name="城市",
                    dimension_code="city_name",
                    role="group_by",
                    alias="城市",
                    is_resolved=True,
                )
            )
        dimension_definitions = (
            (("客户状态",), "客户状态", "cust_status"),
            (("客户类型",), "客户类型", "cust_type"),
            (("客户等级代码", "客户等级"), "客户等级代码", "cust_lvl_cd"),
            (("学历代码", "学历"), "学历代码", "edu_cd"),
            (("性别代码", "性别"), "性别代码", "gender_cd"),
        )
        for keywords, name, dimension_code in dimension_definitions:
            if any(keyword in question for keyword in keywords) and any(
                self._dimension_grouping_requested(question, keyword) for keyword in keywords
            ):
                dimensions.append(
                    QueryDimension(
                        name=name,
                        dimension_code=dimension_code,
                        role="group_by",
                        alias=name,
                        is_resolved=True,
                    )
                )
        if "年龄" in question and "平均年龄" not in question:
            dimensions.append(
                QueryDimension(
                    name="客户年龄",
                    dimension_code="cust_age",
                    role=(
                        "group_by"
                        if self._asks_for_grouping(question) or "分布" in question
                        else "display"
                    ),
                    alias="客户年龄",
                    is_resolved=True,
                )
            )
        explicit_upper_product_terms = ("一级产品分类", "一级产品类别", "一级产品类型")
        upper_product_terms = ("产品大类", *explicit_upper_product_terms)
        lower_product_terms = ("二级产品分类", "二级产品类别", "二级产品类型")
        product_terms = (
            *upper_product_terms,
            *lower_product_terms,
            "产品类型",
            "产品类别",
            "产品分类",
        )
        if any(token in question for token in product_terms):
            if any(token in question for token in upper_product_terms):
                dimensions.append(
                    QueryDimension(
                        name="一级产品分类",
                        dimension_code="up_prdt_type_name",
                        role="group_by",
                        alias="一级产品分类",
                        is_resolved=True,
                    )
                )
            # Historical organizer wording “产品大类” asks for the hierarchy
            # display and remains compatible with its existing two-level output.
            # Explicit “一级/二级产品分类” is a strict single-level request.
            if "产品大类" in question or not any(
                token in question for token in explicit_upper_product_terms
            ):
                lower_name = (
                    "二级产品分类"
                    if any(token in question for token in lower_product_terms)
                    else "产品分类"
                )
                dimensions.append(
                    QueryDimension(
                        name=lower_name,
                        dimension_code="prdt_type_name",
                        role="group_by",
                        alias=lower_name,
                        is_resolved=True,
                    )
                )
        if "账户来源" in question or "账户类型" in question:
            dimensions.append(
                QueryDimension(
                    name="账户来源",
                    dimension_code="sys_source",
                    role="group_by",
                    alias="账户来源",
                    is_resolved=True,
                )
            )
        if "币种" in question:
            dimensions.append(
                QueryDimension(
                    name="币种",
                    dimension_code="ccy",
                    role="group_by",
                    alias="币种",
                    is_resolved=True,
                )
            )
        if any(token in question for token in ("交易日", "交易日期", "每天")):
            dimensions.append(
                QueryDimension(
                    name="交易日",
                    dimension_code="data_dt",
                    role="group_by",
                    alias="交易日",
                    is_resolved=True,
                )
            )
        if any(token in question for token in ("盈亏", "盈利")) and "客户" in question:
            dimensions.append(
                QueryDimension(
                    name="客户",
                    dimension_code="pty_id",
                    role="display",
                    alias="客户",
                    is_resolved=True,
                )
            )
        return dimensions

    def _detect_time_range(self, question: str) -> TimeRange | None:
        first_quarter_terms = ("26年Q1", "2026年Q1", "2026年一季度", "26年第一季度")
        if any(token in question for token in first_quarter_terms):
            return TimeRange(
                label="2026年第一季度",
                start="20260101",
                end="20260331",
                granularity="quarter",
                is_resolved=True,
            )
        if "2026年3月31日" in question or "2026-03-31" in question:
            return TimeRange(
                label="截至2026年3月31日",
                start="20260331",
                end="20260331",
                anchor_date="20260331",
                granularity="day",
                is_resolved=True,
            )
        abbreviated_range = re.search(
            r"(?P<year>20\d{2})年(?P<month>\d{1,2})月(?P<start>\d{1,2})日?\s*(?:至|到)\s*"
            r"(?:(?P<end_year>20\d{2})年)?(?:(?P<end_month>\d{1,2})月)?(?P<end>\d{1,2})日?",
            question,
        )
        if abbreviated_range:
            try:
                year = int(abbreviated_range.group("year"))
                month = int(abbreviated_range.group("month"))
                start = date(year, month, int(abbreviated_range.group("start")))
                end = date(
                    int(abbreviated_range.group("end_year") or year),
                    int(abbreviated_range.group("end_month") or month),
                    int(abbreviated_range.group("end")),
                )
            except ValueError:
                pass
            else:
                return TimeRange(
                    label=f"{start:%Y年%m月%d日}至{end:%Y年%m月%d日}",
                    start=start.strftime("%Y%m%d"),
                    end=end.strftime("%Y%m%d"),
                    granularity="day",
                    is_resolved=True,
                )
        explicit_dates = self._extract_explicit_dates(question)
        if len(explicit_dates) >= 2:
            start, end = explicit_dates[:2]
            return TimeRange(
                label=f"{start[:4]}年{int(start[4:6])}月{int(start[6:])}日至{end[:4]}年{int(end[4:6])}月{int(end[6:])}日",
                start=start,
                end=end,
                granularity="day",
                is_resolved=True,
            )
        if explicit_dates:
            snapshot_date = explicit_dates[0]
            return TimeRange(
                label=f"截至{snapshot_date[:4]}年{int(snapshot_date[4:6])}月{int(snapshot_date[6:])}日",
                start=snapshot_date,
                end=snapshot_date,
                anchor_date=snapshot_date,
                granularity="day",
                is_resolved=True,
            )
        if "26年1月10日" in question and "26年2月15日" in question:
            return TimeRange(
                label="2026年1月10日至2月15日",
                start="20260110",
                end="20260215",
                granularity="day",
                is_resolved=True,
            )
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

    @staticmethod
    def _extract_explicit_dates(question: str) -> list[str]:
        """Parse calendar dates written with Chinese, hyphen, or slash separators.

        Invalid calendar values are ignored instead of becoming an executable
        filter.  This makes the parsing reusable for any official snapshot date,
        rather than encoding one benchmark date in the rule actor.
        """
        pattern = re.compile(
            r"(?P<year>20\d{2})\s*(?:年|-|/)\s*(?P<month>\d{1,2})\s*(?:月|-|/)\s*(?P<day>\d{1,2})(?:日)?"
        )
        parsed: list[str] = []
        for match in pattern.finditer(question):
            try:
                value = date(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day")),
                )
            except ValueError:
                continue
            parsed.append(value.strftime("%Y%m%d"))
        return parsed

    def _detect_grain(self, question: str) -> QueryGrain:
        if "一级营业部" in question and (
            self._asks_for_grouping(question) or "分布" in question or "统计" in question
        ):
            keys = ["up_org_name"]
            if any(
                marker in question
                for marker in ("一级营业部、营业部", "一级营业部和营业部", "一级营业部及营业部")
            ):
                keys.append("org_name")
            return QueryGrain(
                level="organization", keys=keys, description="一级营业部级", is_resolved=True
            )
        if ("营业部" in question or "分支机构" in question) and (
            self._asks_for_grouping(question) or "分布" in question or "统计" in question
        ):
            return QueryGrain(
                level="organization", keys=["org_id"], description="营业部级", is_resolved=True
            )
        explicit_upper_product_terms = ("一级产品分类", "一级产品类别", "一级产品类型")
        if any(token in question for token in ("产品类型", "产品类别", "产品分类", "产品大类")):
            return QueryGrain(
                level="product",
                keys=(
                    ["up_prdt_type_name", "prdt_type_name"]
                    if "产品大类" in question
                    else ["up_prdt_type_name"]
                    if any(token in question for token in explicit_upper_product_terms)
                    else ["prdt_type_name"]
                ),
                description="产品分类级",
                is_resolved=True,
            )
        group_dimensions = {
            "省份": "prov_name",
            "城市": "city_name",
            "客户状态": "cust_status",
            "客户类型": "cust_type",
            "客户等级代码": "cust_lvl_cd",
            "客户等级": "cust_lvl_cd",
            "学历代码": "edu_cd",
            "学历": "edu_cd",
            "性别代码": "gender_cd",
            "性别": "gender_cd",
            "账户来源": "sys_source",
            "账户类型": "sys_source",
            "币种": "ccy",
            "交易日": "data_dt",
            "交易日期": "data_dt",
            "每天": "data_dt",
        }
        grouped_keys = [
            code
            for keyword, code in group_dimensions.items()
            if self._dimension_grouping_requested(question, keyword)
        ]
        if grouped_keys:
            return QueryGrain(
                level="aggregate",
                keys=list(dict.fromkeys(grouped_keys)),
                description="维度分组汇总级",
                is_resolved=True,
            )
        if any(token in question for token in self.COUNT_INTENT_TOKENS):
            return QueryGrain(level="aggregate", keys=[], description="汇总级", is_resolved=True)
        if any(
            token in question
            for token in ("账户来源", "账户类型", "币种", "交易日", "交易日期", "每天")
        ):
            return QueryGrain(
                level="aggregate", keys=[], description="分组汇总级", is_resolved=True
            )
        return QueryGrain(level="customer", keys=["pty_id"], description="客户级", is_resolved=True)

    def _build_output(
        self,
        question: str,
        grain: QueryGrain,
        metrics: list[QueryMetric],
        dimensions: list[QueryDimension],
        filters: list[QueryFilter],
    ) -> QueryOutput:
        filter_codes = {
            query_filter.metric_code for query_filter in filters if query_filter.metric_code
        }
        asks_for_customer_count = any(
            token in question
            for token in ("客户数", "客户数量", "去重客户", "几位客户", "多少位客户", "客户有多少")
        )
        metric_columns = [
            metric.alias or metric.name
            for metric in metrics
            if not (asks_for_customer_count and metric.metric_code in filter_codes)
        ]
        dimension_columns = [dimension.alias or dimension.name for dimension in dimensions]
        limit_match = re.search(r"(?:前\s*|top\s*)(\d+)", question, re.IGNORECASE)
        limit = int(limit_match.group(1)) if limit_match else 100
        if "日均资产" in question and "产品大类" in question:
            # 日均资产和股票交易量仅用于筛选客户；最终问题询问的是这些
            # 客户在期末持有的产品大类，不能把筛选指标误当作分组输出指标。
            return QueryOutput(
                format="table",
                columns=["产品大类", "产品分类", "持仓市值"],
                limit=limit,
            )
        if grain.level == "aggregate" and not dimensions:
            return QueryOutput(
                format="summary", columns=metric_columns or ["客户数量"], limit=limit
            )
        columns = dimension_columns or (["客户"] if grain.level == "customer" else [])
        columns.extend(column for column in metric_columns if column not in columns)
        return QueryOutput(format="table", columns=columns or ["客户数量"], limit=limit)

    def _build_data_requirements(
        self,
        metrics: list[QueryMetric],
        filters: list[QueryFilter],
        dimensions: list[QueryDimension],
    ) -> DataRequirement:
        domains: set[str] = {"customer"}
        candidate_tables: set[str] = {"ads_cust_info_d"}

        metric_codes = {metric.metric_code for metric in metrics}
        filter_codes = {query_filter.metric_code for query_filter in filters}
        all_codes = metric_codes | filter_codes

        if {
            "total_asset",
            "average_total_asset",
            "normal_total_asset",
            "credit_total_asset",
            "cash_asset",
            "daily_average_asset",
        } & all_codes:
            domains.add("asset")
            candidate_tables.add("dws_cust_aset_d")
        if {
            "trade_amount",
            "trade_fee",
            "buy_amount",
            "average_trade_amount",
            "trade_quantity",
            "bidirectional_trade_customer",
        } & all_codes:
            domains.add("trade")
            candidate_tables.update({"dwd_cust_tran_d", "dim_product"})
        finance_metric_codes = {
            "net_cash_flow",
            "net_cash_inflow",
            "cash_in_amount",
            "transfer_amount",
            "assignment_amount",
        }
        if finance_metric_codes & all_codes:
            domains.add("finance")
            candidate_tables.add("dws_cust_fin_d")
        if "profit_loss" in all_codes:
            domains.update({"asset", "finance"})
            candidate_tables.update({"dws_cust_aset_d", "dws_cust_fin_d"})
        if {
            "holding_market_value",
            "holding_quantity",
            "distinct_holding_product_count",
        } & all_codes:
            domains.add("holding")
            candidate_tables.update({"dwd_cust_hold_d", "dim_product"})

        field_codes = {query_filter.field_code for query_filter in filters}
        if {"cust_lvl_cd", "gender_cd"} & field_codes:
            candidate_tables.add("dim_public")
        if {"prdt_name", "prdt_type_name", "up_prdt_type_id"} & field_codes:
            candidate_tables.add("dim_product")
        if {
            dimension.dimension_code
            for dimension in dimensions
            if dimension.dimension_code is not None
        } & {"org_name", "up_org_name"}:
            candidate_tables.add("dim_branch")

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

        if all(
            token not in question
            for token in [
                "客户",
                "营业部",
                "分支机构",
                "产品",
                "基金",
                "资产",
                "交易",
                "持仓",
                "盈亏",
                "流入",
                "账户来源",
                "币种",
            ]
        ):
            clarifications.append(
                ClarificationQuestion(
                    field="查询主体",
                    question="请确认本次查询的主体。",
                    reason="当前问题无法判断是查询客户、产品还是服务经理。",
                    options=["客户", "产品", "营业部"],
                )
            )

        return clarifications

    def _detect_assumptions(
        self, question: str, clarifications: list[ClarificationQuestion]
    ) -> list[PlanAssumption]:
        if clarifications:
            return []
        assumptions: list[PlanAssumption] = []
        if "不同客户年龄段资产分布" in question:
            assumptions.extend(
                [
                    PlanAssumption(
                        field="客户快照日期",
                        value="20260531",
                        reason="官方年龄段资产分布示例以 20260531 客户快照分段。",
                        source="business_term",
                    ),
                    PlanAssumption(
                        field="资产快照日期",
                        value="20260331",
                        reason="官方年龄段资产分布示例以 20260331 资产快照汇总。",
                        source="business_term",
                    ),
                ]
            )
        elif "资产" in question and "当前" not in question and "日均资产" not in question:
            assumptions.append(
                PlanAssumption(
                    field="资产",
                    value="最新数据日期资产",
                    reason="用户未指定时点，默认按官方数据的最新日期统计资产。",
                )
            )
        if "年龄" in question and "分布" in question:
            assumptions.append(
                PlanAssumption(
                    field="年龄分组",
                    value=["<30", "30-49", "50-59", ">=60"],
                    reason="用户明确给出官方年龄分段，按分段汇总输出。",
                    source="user",
                )
            )
        return assumptions

    def _extract_amount_threshold(self, question: str) -> dict[str, int | str] | None:
        thresholds = self._extract_amount_thresholds(question)
        asset_threshold = next(
            (item for item in thresholds if item["metric_code"] == "total_asset"), None
        )
        return asset_threshold or (thresholds[0] if thresholds else None)

    def _extract_amount_thresholds(self, question: str) -> list[dict[str, int | str]]:
        thresholds: list[dict[str, int | str]] = []
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(万|元)", question):
            raw_value = match.group(0)
            value = float(match.group(1)) * (10000 if match.group(2) == "万" else 1)
            # A question can contain several amounts, for example "日均资产超过
            # 30万且交易金额超过10万".  Attribute each threshold to the closest
            # preceding metric phrase instead of letting the next predicate leak
            # into its context.
            prefix = question[max(0, match.start() - 32) : match.start()]
            suffix = question[match.end() : min(len(question), match.end() + 6)]
            daily_average_position = prefix.rfind("日均资产")
            metric_positions = {
                "daily_average_asset": daily_average_position,
                "cash_in_amount": prefix.rfind("现金流入"),
                "trade_fee": max(prefix.rfind(token) for token in ("交易费用", "手续费")),
                "trade_amount": max(
                    prefix.rfind(token)
                    for token in ("交易", "成交", "买入", "卖出", "交易量")
                ),
                "holding_market_value": max(prefix.rfind(token) for token in ("持仓", "市值")),
                # The shorter “资产” token is part of “日均资产”; it must not
                # override the more specific metric phrase.
                "total_asset": prefix.rfind("资产") if daily_average_position < 0 else -1,
            }
            nearest_metric, nearest_position = max(
                metric_positions.items(), key=lambda item: item[1]
            )
            if nearest_position >= 0:
                metric_code = nearest_metric
            elif "日均资产" in suffix:
                metric_code = "daily_average_asset"
            elif "现金流入" in suffix:
                metric_code = "cash_in_amount"
            elif any(token in suffix for token in ("交易费用", "手续费")):
                metric_code = "trade_fee"
            elif any(token in suffix for token in ("交易", "成交", "买入", "卖出", "交易量")):
                metric_code = "trade_amount"
            elif any(token in suffix for token in ("持仓", "市值")):
                metric_code = "holding_market_value"
            else:
                metric_code = "total_asset"
            comparison_context = f"{prefix}{suffix}"
            operator = (
                ">="
                if any(
                    marker in comparison_context
                    for marker in ("不少于", "不低于", "至少", "达到", "达", ">=")
                )
                else ">"
            )
            thresholds.append(
                {
                    "raw": raw_value,
                    "value": int(value),
                    "metric_code": metric_code,
                    "operator": operator,
                }
            )
        return thresholds

    @staticmethod
    def _is_bidirectional_trade_question(question: str) -> bool:
        has_buy = "买入" in question
        has_sell = "卖出" in question
        return (
            has_buy and has_sell and any(token in question for token in ("同时", "均", "都"))
        ) or (
            "双向交易" in question or "买卖双向" in question
        )

    @staticmethod
    def _is_multi_product_holding_question(question: str) -> bool:
        return (
            any(token in question for token in ("持有", "持仓"))
            and "产品" in question
            and any(token in question for token in ("不同", "去重", "多只", "多种"))
        )

    @staticmethod
    def _extract_distinct_product_threshold(question: str) -> int | None:
        match = re.search(
            r"(?:至少|不少于|不低于|>=|大于等于)\s*(?:持有)?\s*(\d+|一|二|两|三|四|五|六|七|八|九|十)\s*(?:只|种|个)?\s*(?:不同|去重)?\s*产品",
            question,
        )
        if match is None:
            return None
        numeral = match.group(1)
        chinese_numerals = {
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
            "十": 10,
        }
        return int(numeral) if numeral.isdigit() else chinese_numerals[numeral]

    def _extract_trade_count_threshold(self, question: str) -> int | None:
        if "交易次数" not in question:
            return None
        match = re.search(r"(?:交易次数)?(?:超过|大于|>)\s*(\d+)\s*次?", question)
        if match:
            return int(match.group(1))
        return None

    def _asks_for_grouping(self, question: str) -> bool:
        return any(token in question for token in ["按", "汇总", "分组"])

    def _dimension_grouping_requested(self, question: str, keyword: str) -> bool:
        """Recognize a requested output grouping without mistaking a filter for one."""
        compact_question = re.sub(r"\s+", "", question)
        return (
            ("按" in compact_question and keyword in compact_question)
            or any(
                marker in compact_question
                for marker in (
                    f"{keyword}分布",
                    f"{keyword}统计",
                    f"{keyword}汇总",
                    f"{keyword}分析",
                    f"{keyword}展示",
                )
            )
        )

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
