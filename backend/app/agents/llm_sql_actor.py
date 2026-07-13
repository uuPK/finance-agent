import json
from dataclasses import dataclass
from textwrap import dedent
from typing import Any, Literal

from app.llm.json_parser import extract_json_object
from app.llm.protocols import SupportsLLMComplete
from app.llm.schemas import LLMMessage
from app.schemas.query_plan import QueryPlan
from app.schemas.review import ReviewDecision
from app.schemas.sql import SQLDraft

SQLActorSource = Literal["llm", "rule_fallback", "failed"]


@dataclass(slots=True)
class SQLBuildResult:
    draft: SQLDraft | None
    source: SQLActorSource
    repair_attempt: int = 0
    llm_error: str | None = None
    llm_raw_response: str | None = None
    llm_model: str | None = None
    llm_provider: str | None = None


class LLMSQLActor:
    """Generate PostgreSQL SELECT SQL from an approved QueryPlan."""

    def __init__(self, llm_service: SupportsLLMComplete | None) -> None:
        self.llm_service = llm_service

    async def build(
        self,
        question: str,
        query_plan: QueryPlan,
        metadata_context: dict[str, Any] | None = None,
        previous_sql: str | None = None,
        critic_feedback: list[ReviewDecision] | None = None,
        repair_attempt: int = 0,
    ) -> SQLBuildResult:
        if self.llm_service is None:
            return SQLBuildResult(
                draft=None,
                source="failed",
                repair_attempt=repair_attempt,
                llm_error="LLM service is required for SQL generation.",
            )

        try:
            response = await self.llm_service.complete(
                messages=self._build_messages(
                    question=question,
                    query_plan=query_plan,
                    metadata_context=metadata_context or {},
                    previous_sql=previous_sql,
                    critic_feedback=critic_feedback,
                ),
                temperature=0.0,
                max_tokens=2600,
                response_format={"type": "json_object"},
            )
            data = extract_json_object(response.content)
            draft = SQLDraft.model_validate(data)
            return SQLBuildResult(
                draft=draft,
                source="llm",
                repair_attempt=repair_attempt,
                llm_raw_response=response.content,
                llm_model=response.model,
                llm_provider=response.provider,
            )
        except Exception as exc:
            return SQLBuildResult(
                draft=None,
                source="failed",
                repair_attempt=repair_attempt,
                llm_error=f"{type(exc).__name__}: {exc}",
            )

    def _build_messages(
        self,
        question: str,
        query_plan: QueryPlan,
        metadata_context: dict[str, Any],
        previous_sql: str | None,
        critic_feedback: list[ReviewDecision] | None,
    ) -> list[LLMMessage]:
        draft_schema = json.dumps(SQLDraft.model_json_schema(), ensure_ascii=False)
        query_plan_json = json.dumps(
            query_plan.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            indent=2,
        )
        metadata_json = json.dumps(metadata_context, ensure_ascii=False, indent=2)

        repair_context = ""
        if previous_sql and critic_feedback:
            feedback_json = json.dumps(
                [
                    feedback.model_dump(mode="json", exclude_none=True)
                    for feedback in critic_feedback
                ],
                ensure_ascii=False,
                indent=2,
            )
            repair_context = dedent(
                f"""

                上一版 SQL：
                {previous_sql}

                SQL review feedback：
                {feedback_json}

                当前任务模式：根据 SQL review feedback 修复上一版 SQL。
                修复要求：
                - 优先修复 hard guardrail 或 SQLCritic 指出的失败项。
                - 不要删除 QueryPlan 中明确要求的指标、过滤、时间窗口、粒度和输出字段。
                - 不要为通过审核而弱化 WHERE 条件或放大返回范围。
                - 必须继续使用 metadata context 中的真实表、真实字段和 join 路径。
                """
            )

        user_prompt = dedent(
            f"""
            用户问题：
            {question}

            已审核通过的 QueryPlan：
            {query_plan_json}

            Metadata context，来自当前 PostgreSQL 与 metadata 表：
            {metadata_json}
            {repair_context}

            SQLDraft JSON Schema：
            {draft_schema}

            输出要求：
            - 只输出一个合法 JSON object。
            - JSON 必须能被 SQLDraft schema 校验通过。
            - sql 字段只能包含一条 PostgreSQL SELECT 查询。
            - 不要输出 Markdown、解释、注释或额外文本。
            """
        ).strip()

        return [
            LLMMessage(role="system", content=_SQL_ACTOR_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]


_SQL_ACTOR_SYSTEM_PROMPT = dedent(
    """
    Semantic contract rules:
    - semantic_contract in Metadata context is authoritative. Follow its table-grain, time-window,
      formula, and sensitive-column rules exactly.
    - A *_90d view already satisfies the 90-day window. Do not add an unsupported raw-date predicate.
    - Never select or suggest any column in sensitive_columns_never_select, including while repairing SQL.
    - Use a fact table whose grain supports the requested dimension: product analysis requires a
      product-grain trade table; campaign analysis requires campaign/touch tables.
    - Use metric_code as the output alias for aggregated metrics whenever possible.
    - For "not held" / "without fund" conditions, write a correlated NOT EXISTS subquery over the
      matching product type and snapshot date. A LEFT JOIN ... IS NULL is not equivalent.
    - For net-outflow rankings, keep the negative-flow filter, convert the displayed amount to a
      positive outflow amount, and order that amount descending.
    - When semantic_contract.reference_date is present, use that literal as the relative-time anchor
      instead of CURRENT_DATE.
    - For campaign benchmark output, prefer campaign_code over campaign_name unless the user
      explicitly requests names.
    - For customer-facing detail output, select customer_no as the stable business identifier.
      customer_id is an internal join key and is not a substitute for customer_no.
    - For campaign response_rate, use responded touch count divided by all touch count; keep any
      responded customer-count metric separate from the rate denominator.

    你是证券客户营销问数系统的 SQLActor。你的任务是把已经通过审核的 QueryPlan
    转换成 PostgreSQL SELECT SQL。你只生成 SQLDraft JSON，不执行 SQL。

    输出契约：
    1. 只输出一个 JSON object，必须符合 SQLDraft schema。
    2. sql 必须是一条 PostgreSQL SELECT 查询，禁止多语句。
    3. SQL 必须包含 LIMIT，且 LIMIT 不得超过 QueryPlan.output.limit 和 safety.max_rows。
    4. 禁止 INSERT、UPDATE、DELETE、DROP、ALTER、TRUNCATE、CREATE。
    5. 禁止 SELECT *，必须显式选择列或表达式并使用清晰别名。
    6. 默认不得返回手机号、身份证号、银行卡号、详细地址等敏感字段。
    7. 必须尽量覆盖 QueryPlan 的 metrics、filters、time_range、grain、output.columns。

    元数据策略：
    - metadata context 是 SQL 表结构的唯一可信来源。
    - 如果 metadata context 提供了表、字段、指标公式和 join_path，必须使用其中的真实表名、
      真实字段名和 join 路径。
    - 如果 metadata context 中有 table_allowlist，SQL 只能使用白名单中的表或视图。
    - 如果 metadata context 中有 allowed_columns_by_table，带表别名的字段必须来自对应表字段列表。
    - 如果 metadata context.source != "database" 或 table_count=0，说明 schema context 加载失败；
      此时应只在 QueryPlan 已给出明确表字段时生成低置信度 SQL，并在 assumptions 中说明
      "schema_context_unavailable"。
    - 不要编造 metadata context 中不存在的表、字段、指标公式或 join 路径。
    - 当前资产优先使用 mart.customer_current_asset。
    - 近 90 天交易次数/金额优先使用 mart.customer_trade_90d。
    - 近 90 天净流入优先使用 mart.customer_net_flow_90d。

    粒度策略：
    - grain.level=customer：通常 SELECT customer_id，并按 customer_id 分组或返回客户级行。
    - grain.level=manager：通常 SELECT manager_id，并按 manager_id 分组。
    - grain.level=aggregate：返回汇总指标，可不按实体分组。
    - metric aggregation 必须与 QueryPlan.metrics 中的 aggregation 尽量一致。

    数量与总数策略：
    - 如果 QueryPlan.intent=metric_query 或 grain.level=aggregate，且 metrics 中包含
      customer_count / count / count_distinct，SQL 应返回一行汇总结果，使用
      count(distinct customer_id) as customer_count 或 count(*) as total_count。
    - 汇总 count SQL 仍必须包含 LIMIT 1。
    - 如果用户明确要求“列表/名单/明细”同时要求“总数/共多少”，SQL 应先用 CTE 构造 base 明细，
      再在外层 SELECT 中加入 count(*) over() as total_count，并保留客户级明细列。
    - 如果用户只要求列表/名单/明细，不要为了回答方便强制计算 total_count，优先保证速度。
    - AnswerActor 会优先读取 total_count、customer_count、count、客户数量等字段；没有这些字段时，
      row_count 只代表本次 SQL 实际返回行数，不代表全量命中数。

    正例：
    QueryPlan 要求客户级列表、current_total_asset > 500000、trade_count_90d > 3。
    好的 SQLDraft：
    {
      "sql": "SELECT c.customer_no, a.total_asset, t.trade_count_90d FROM mart.customer_info c JOIN mart.customer_current_asset a ON a.customer_id = c.customer_id LEFT JOIN mart.customer_trade_90d t ON t.customer_id = c.customer_id WHERE a.total_asset > 500000 AND COALESCE(t.trade_count_90d, 0) > 3 LIMIT 100",
      "dialect": "postgres",
      "tables": ["customer_info", "customer_current_asset", "customer_trade_90d"],
      "columns": ["customer_no", "total_asset", "trade_count_90d"],
      "assumptions": [],
      "confidence": 0.88
    }
    这个例子通过，因为它是只读 SELECT，包含 LIMIT，并覆盖了资产过滤、交易次数过滤和时间窗口。

    正例：数量查询
    QueryPlan 要求汇总当前资产大于50万且近90天交易次数大于3的客户数量。
    好的 SQLDraft：
    {
      "sql": "SELECT COUNT(DISTINCT c.customer_id) AS customer_count FROM mart.customer_info c JOIN mart.customer_current_asset a ON a.customer_id = c.customer_id LEFT JOIN mart.customer_trade_90d t ON t.customer_id = c.customer_id WHERE a.total_asset > 500000 AND COALESCE(t.trade_count_90d, 0) > 3 LIMIT 1",
      "dialect": "postgres",
      "tables": ["customer_info", "customer_current_asset", "customer_trade_90d"],
      "columns": ["customer_count"],
      "assumptions": [],
      "confidence": 0.9
    }

    正例：列表同时带总数
    用户要求客户列表并要求总数时，可以使用窗口函数：
    {
      "sql": "WITH base AS (SELECT c.customer_no, a.total_asset, t.trade_count_90d FROM mart.customer_info c JOIN mart.customer_current_asset a ON a.customer_id = c.customer_id LEFT JOIN mart.customer_trade_90d t ON t.customer_id = c.customer_id WHERE a.total_asset > 500000 AND COALESCE(t.trade_count_90d, 0) > 3) SELECT customer_no, total_asset, trade_count_90d, COUNT(*) OVER() AS total_count FROM base LIMIT 100",
      "dialect": "postgres",
      "tables": ["customer_info", "customer_current_asset", "customer_trade_90d"],
      "columns": ["customer_no", "total_asset", "trade_count_90d", "total_count"],
      "assumptions": [],
      "confidence": 0.88
    }

    反例：
    {
      "sql": "SELECT * FROM customer_info",
      "dialect": "postgres",
      "tables": ["customer_info"],
      "columns": ["*"],
      "assumptions": [],
      "confidence": 0.9
    }
    这个例子失败，因为它 SELECT *、缺少 QueryPlan 过滤条件、没有 LIMIT。
    """
).strip()
