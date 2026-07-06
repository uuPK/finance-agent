import json
from dataclasses import dataclass
from textwrap import dedent
from typing import Literal

from app.llm.json_parser import extract_json_object
from app.llm.protocols import SupportsLLMComplete
from app.llm.schemas import LLMMessage
from app.schemas.query_plan import QueryPlan
from app.schemas.review import ReviewDecision
from app.schemas.sql import SQLDraft


SQLCriticStatus = Literal["reviewed", "failed"]


@dataclass(slots=True)
class LLMSQLCriticResult:
    status: SQLCriticStatus
    decision: ReviewDecision | None = None
    llm_error: str | None = None
    llm_raw_response: str | None = None
    llm_model: str | None = None
    llm_provider: str | None = None


class LLMSQLCritic:
    """Review whether generated SQL faithfully implements the approved QueryPlan."""

    def __init__(self, llm_service: SupportsLLMComplete | None) -> None:
        self.llm_service = llm_service

    async def review(
        self,
        query_plan: QueryPlan,
        sql_draft: SQLDraft,
        hard_checks: list[ReviewDecision],
    ) -> LLMSQLCriticResult:
        if self.llm_service is None:
            return LLMSQLCriticResult(
                status="failed",
                llm_error="LLM service is required for SQL semantic review.",
            )

        try:
            response = await self.llm_service.complete(
                messages=self._build_messages(query_plan, sql_draft, hard_checks),
                temperature=0.0,
                max_tokens=1800,
                response_format={"type": "json_object"},
            )
            data = extract_json_object(response.content)
            decision = ReviewDecision.model_validate(data)
            if decision.stage != "sql_review":
                decision = decision.model_copy(update={"stage": "sql_review"})
            return LLMSQLCriticResult(
                status="reviewed",
                decision=decision,
                llm_raw_response=response.content,
                llm_model=response.model,
                llm_provider=response.provider,
            )
        except Exception as exc:
            return LLMSQLCriticResult(
                status="failed",
                llm_error=f"{type(exc).__name__}: {exc}",
            )

    def _build_messages(
        self,
        query_plan: QueryPlan,
        sql_draft: SQLDraft,
        hard_checks: list[ReviewDecision],
    ) -> list[LLMMessage]:
        review_schema = json.dumps(ReviewDecision.model_json_schema(), ensure_ascii=False)
        query_plan_json = json.dumps(
            query_plan.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            indent=2,
        )
        sql_draft_json = json.dumps(
            sql_draft.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            indent=2,
        )
        hard_checks_json = json.dumps(
            [check.model_dump(mode="json", exclude_none=True) for check in hard_checks],
            ensure_ascii=False,
            indent=2,
        )

        user_prompt = dedent(
            f"""
            Approved QueryPlan：
            {query_plan_json}

            Generated SQLDraft：
            {sql_draft_json}

            SQL hard guardrail checks：
            {hard_checks_json}

            ReviewDecision JSON Schema：
            {review_schema}

            输出要求：
            - 只输出一个合法 JSON object。
            - JSON 必须能被 ReviewDecision schema 校验通过。
            - stage 必须是 sql_review。
            - 不要输出 Markdown、解释、SQL、注释或额外文本。
            """
        ).strip()

        return [
            LLMMessage(role="system", content=_SQL_CRITIC_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]


_SQL_CRITIC_SYSTEM_PROMPT = dedent(
    """
    你是 SQLCritic，负责审核 SQLDraft 是否忠实实现已通过审核的 QueryPlan。
    你只审核，不重写完整 SQL，不执行 SQL。

    审核边界：
    1. hard guardrail 是安全 veto。若 hard check failed，你必须 passed=false。
    2. 你关注 QueryPlan-to-SQL 的语义一致性：指标、过滤、时间、粒度、输出字段。
    3. 表名、字段名、敏感字段和 LIMIT 已由 hard guardrail 基于 schema context 校验；
       你不能覆盖 hard guardrail 的失败结论。
    4. 如果 SQL 与 QueryPlan 无关、遗漏关键条件、粒度错误或返回敏感字段，必须失败。

    必查项：
    - SQL 是否覆盖所有 QueryPlan.metrics。
    - SQL 是否覆盖所有 QueryPlan.filters。
    - SQL 是否覆盖全局 time_range 或 metric time_window。
    - SQL 的 GROUP BY / HAVING 是否匹配 QueryPlan.grain 和聚合过滤。
    - SQL 的 SELECT 字段是否能支撑 output.columns。
    - SQL 是否遗漏 LIMIT 或放宽 QueryPlan 约束。

    评分和 passed 规则：
    - 90-100：语义完整，passed=true。
    - 75-89：小瑕疵但不影响执行语义，passed=true。
    - 50-74：漏掉某个过滤、时间或输出字段，passed=false。
    - 0-49：安全失败、SQL 与 QueryPlan 不一致、错误粒度，passed=false。

    正例：
    QueryPlan 要求 current_total_asset > 500000、trade_count_3m > 3、last_3_months、
    customer 粒度。SQL 包含资产 WHERE、交易日期 WHERE、GROUP BY customer_id、
    HAVING COUNT(trade_id) > 3、LIMIT。
    应输出 passed=true，evidence 包含 filters_covered、time_window_covered、grain_covered。

    反例：
    QueryPlan 要求 trade_count_3m > 3，但 SQL 统计所有历史交易，没有 trade_date 条件。
    应输出：
    {
      "passed": false,
      "score": 55,
      "stage": "sql_review",
      "error_type": "missing_time_filter",
      "reason": "SQL 未实现 QueryPlan 要求的近三个月交易窗口。",
      "evidence": ["QueryPlan metric: trade_count_3m", "SQL has no trade_date time filter"],
      "repair_hint": "为交易表增加近三个月时间条件，例如 trade_date >= CURRENT_DATE - INTERVAL '3 months'。",
      "clarification_questions": [],
      "confidence": 0.9
    }
    """
).strip()
