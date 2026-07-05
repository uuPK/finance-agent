import json
from dataclasses import dataclass
from textwrap import dedent
from typing import Literal

from app.llm.json_parser import extract_json_object
from app.llm.protocols import SupportsLLMComplete
from app.llm.schemas import LLMMessage
from app.schemas.query_plan import QueryPlan
from app.schemas.review import ReviewDecision


CriticStatus = Literal["reviewed", "skipped"]


@dataclass(slots=True)
class LLMPlanCriticResult:
    status: CriticStatus
    decision: ReviewDecision | None = None
    llm_error: str | None = None
    llm_raw_response: str | None = None
    llm_model: str | None = None
    llm_provider: str | None = None


class LLMPlanCritic:
    """Semantic critic for QueryPlan after deterministic hard checks."""

    def __init__(self, llm_service: SupportsLLMComplete | None) -> None:
        self.llm_service = llm_service

    async def review(
        self, plan: QueryPlan, hard_checks: list[ReviewDecision]
    ) -> LLMPlanCriticResult:
        if self.llm_service is None:
            return LLMPlanCriticResult(
                status="skipped",
                llm_error="LLM service is not available or API key is not configured.",
            )

        try:
            response = await self.llm_service.complete(
                messages=self._build_messages(plan, hard_checks),
                temperature=0.0,
                max_tokens=1800,
                response_format={"type": "json_object"},
            )
            data = extract_json_object(response.content)
            decision = ReviewDecision.model_validate(data)
            if decision.stage != "query_plan_review":
                decision = decision.model_copy(update={"stage": "query_plan_review"})
            return LLMPlanCriticResult(
                status="reviewed",
                decision=decision,
                llm_raw_response=response.content,
                llm_model=response.model,
                llm_provider=response.provider,
            )
        except Exception as exc:
            return LLMPlanCriticResult(
                status="skipped",
                llm_error=f"{type(exc).__name__}: {exc}",
            )

    def _build_messages(
        self, plan: QueryPlan, hard_checks: list[ReviewDecision]
    ) -> list[LLMMessage]:
        review_schema = json.dumps(ReviewDecision.model_json_schema(), ensure_ascii=False)
        plan_json = json.dumps(
            plan.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            indent=2,
        )
        hard_review_json = json.dumps(
            [check.model_dump(mode="json", exclude_none=True) for check in hard_checks],
            ensure_ascii=False,
            indent=2,
        )
        user_prompt = dedent(
            f"""
            待审核 QueryPlan：
            {plan_json}

            已完成的硬条件审核：
            {hard_review_json}

            ReviewDecision JSON Schema：
            {review_schema}

            请只输出一个合法 JSON object，不要输出 Markdown、解释或 SQL。
            """
        ).strip()

        return [
            LLMMessage(role="system", content=_PLAN_CRITIC_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]


_PLAN_CRITIC_SYSTEM_PROMPT = dedent(
    """
    你是证券客户营销问数系统的 QueryPlanCritic，负责审核 QueryPlan 的语义正确性。
    硬条件已经由程序完成；你只补充程序难以判断的业务语义和需求一致性。

    审核重点：
    1. 用户明示的主体、指标、时间窗口、过滤条件、粒度是否完整保留。
    2. 是否把不明确业务词误判成确定条件，例如“高净值客户”“活跃客户”。
    3. needs_clarification 是否真的提出了关键澄清问题。
    4. 是否凭空编造了表、字段、指标、口径或敏感字段。
    5. 输出粒度是否合理：客户名单应是 customer，按经理汇总应是 manager。

    打分建议：
    - 90-100：可以进入下一步，只有小的表达瑕疵。
    - 70-89：基本可用但存在轻微缺失，passed 可为 true，但 repair_hint 要指出改进。
    - 0-69：缺失关键约束、擅自猜口径、粒度错误或违背安全要求，passed 必须为 false。

    正例：
    用户问“找出高净值客户”，计划返回 needs_clarification 并询问资产门槛。
    审核应输出：
    {
      "passed": true,
      "score": 92,
      "stage": "query_plan_review",
      "reason": "不确定口径已被澄清问题覆盖。",
      "evidence": ["high_net_worth_threshold_clarified"],
      "repair_hint": null,
      "clarification_questions": [],
      "confidence": 0.9
    }

    反例：
    用户问“找出高净值客户”，计划直接假设“当前资产大于100万”并 ready。
    审核应输出：
    {
      "passed": false,
      "score": 40,
      "stage": "query_plan_review",
      "error_type": "guessed_business_definition",
      "reason": "计划擅自假设高净值客户门槛，用户未确认该业务口径。",
      "evidence": ["assumed_current_total_asset_gt_1000000"],
      "repair_hint": "需要先询问高净值客户资产门槛。",
      "clarification_questions": [],
      "confidence": 0.92
    }

    输出必须符合 ReviewDecision schema，stage 必须是 query_plan_review。
    """
).strip()
