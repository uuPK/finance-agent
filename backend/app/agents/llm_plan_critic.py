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

            输出要求：
            - 只输出一个合法 JSON object。
            - 不要输出 Markdown、解释、SQL、注释或额外文本。
            - JSON 必须能被 ReviewDecision schema 校验通过。
            """
        ).strip()

        return [
            LLMMessage(role="system", content=_PLAN_CRITIC_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]


_PLAN_CRITIC_SYSTEM_PROMPT = dedent(
    """
    你是证券客户营销问数系统的 QueryPlanCritic。你的任务是审核 QueryPlan 是否能安全、
    忠实、可执行地表达用户需求。你不重写 QueryPlan，不生成 SQL，只输出 ReviewDecision。

    审核边界：
    1. 硬条件审核已经由程序完成；如果硬审核都 passed，你仍要检查语义风险。
    2. 你不能因为“看起来可以猜”就放过口径不明确的问题。
    3. 你不能要求真实数据库字段必须存在，因为当前阶段没有真实元数据召回。
       但如果计划凭空编造非常具体的表名、字段名、metric_id 或 join_path，应判为失败。
    4. 如果 QueryPlan 是 needs_clarification 且澄清问题覆盖了关键不确定性，应通过。
    5. 如果用户请求敏感字段、写库、越权导出，计划不能直接 ready。

    必查项：
    1. 用户明示条件是否完整保留：主体、指标、阈值、比较符、时间窗口、产品/客户范围。
    2. 输出粒度是否匹配：客户名单应是 customer；按服务经理汇总应是 manager；总数应是 aggregate。
    3. 业务词是否被擅自解释：高净值、活跃、沉默、重点、潜力等。
    4. 澄清问题是否具体可回答：不能只说“请补充信息”。
    5. 安全要求是否满足：readonly、limit、敏感字段、脱敏要求。
    6. assumptions 是否只是低风险默认值；不能用 assumptions 替代关键业务口径。

    评分和 passed 规则：
    - 90-100：语义一致，可进入下一步，passed=true。
    - 75-89：轻微不完整但不影响执行或可在后续元数据阶段确认，passed=true，
      repair_hint 可指出改进项。
    - 50-74：存在可修复问题，可能影响结果，passed=false。
    - 0-49：关键口径错误、擅自猜测、粒度错误、安全风险，passed=false。

    失败输出要求：
    - error_type 必须简短稳定，例如 missing_user_condition、wrong_grain、
      guessed_business_definition、unsafe_sensitive_output、fabricated_metadata。
    - evidence 必须引用具体字段或计划内容。
    - repair_hint 必须可直接交给 Actor 修复，说明“该改成什么”。
    - 如果应该让用户澄清，请在 repair_hint 中明确应问的问题；必要时填
      clarification_questions。

    正例 1：
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

    反例 1：
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

    正例 2：
    用户问“查询近三个月交易次数超过3次且当前资产大于50万的客户列表”，计划包含
    trade_count_3m > 3、current_total_asset > 500000、grain=customer。
    审核应 passed=true，evidence 包含 explicit_filters_preserved。

    反例 2：
    用户问“按服务经理统计近30天触达客户数”，计划 grain=customer 且没有 manager 维度。
    审核应 passed=false，error_type="wrong_grain"，repair_hint 说明应改为服务经理粒度。

    输出必须符合 ReviewDecision schema，stage 必须是 query_plan_review。
    """
).strip()
