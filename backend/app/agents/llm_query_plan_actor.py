import json
from dataclasses import dataclass
from textwrap import dedent
from typing import Literal

from app.agents.query_plan_actor import RuleBasedQueryPlanActor
from app.llm.json_parser import extract_json_object
from app.llm.protocols import SupportsLLMComplete
from app.llm.schemas import LLMMessage
from app.schemas.query_plan import QueryPlan
from app.schemas.review import ReviewDecision


ActorSource = Literal["llm", "rule_fallback"]


@dataclass(slots=True)
class QueryPlanBuildResult:
    plan: QueryPlan
    source: ActorSource
    repair_attempt: int = 0
    llm_error: str | None = None
    llm_raw_response: str | None = None
    llm_model: str | None = None
    llm_provider: str | None = None


class LLMQueryPlanActor:
    """Build QueryPlan with an LLM, falling back to the deterministic actor."""

    def __init__(
        self,
        llm_service: SupportsLLMComplete | None,
        fallback_actor: RuleBasedQueryPlanActor | None = None,
    ) -> None:
        self.llm_service = llm_service
        self.fallback_actor = fallback_actor or RuleBasedQueryPlanActor()

    async def build(
        self,
        question: str,
        fallback_plan: QueryPlan | None = None,
        previous_plan: QueryPlan | None = None,
        critic_feedback: list[ReviewDecision] | None = None,
        repair_attempt: int = 0,
    ) -> QueryPlanBuildResult:
        fallback = fallback_plan or previous_plan or self.fallback_actor.build(question)
        if self.llm_service is None:
            return QueryPlanBuildResult(
                plan=fallback,
                source="rule_fallback",
                repair_attempt=repair_attempt,
                llm_error="LLM service is not available or API key is not configured.",
            )

        try:
            response = await self.llm_service.complete(
                messages=self._build_messages(question, previous_plan, critic_feedback),
                temperature=0.0,
                max_tokens=3000,
                response_format={"type": "json_object"},
            )
            data = extract_json_object(response.content)
            plan = QueryPlan.model_validate(data)
            if plan.question != question:
                plan = plan.model_copy(update={"question": question})
            return QueryPlanBuildResult(
                plan=plan,
                source="llm",
                repair_attempt=repair_attempt,
                llm_raw_response=response.content,
                llm_model=response.model,
                llm_provider=response.provider,
            )
        except Exception as exc:
            return QueryPlanBuildResult(
                plan=fallback,
                source="rule_fallback",
                repair_attempt=repair_attempt,
                llm_error=f"{type(exc).__name__}: {exc}",
            )

    def _build_messages(
        self,
        question: str,
        previous_plan: QueryPlan | None,
        critic_feedback: list[ReviewDecision] | None,
    ) -> list[LLMMessage]:
        schema = json.dumps(QueryPlan.model_json_schema(), ensure_ascii=False)
        repair_context = ""
        if previous_plan is not None and critic_feedback:
            previous_plan_json = json.dumps(
                previous_plan.model_dump(mode="json", exclude_none=True),
                ensure_ascii=False,
                indent=2,
            )
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

                上一版 QueryPlan：
                {previous_plan_json}

                Critic 反馈：
                {feedback_json}

                请根据 critic 反馈修复上一版计划。只能修复与反馈相关的问题，并继续忠实保留用户明示条件。
                """
            )

        user_prompt = dedent(
            f"""
            用户问题：
            {question}
            {repair_context}

            QueryPlan JSON Schema：
            {schema}

            请只输出一个合法 JSON object，不要输出 Markdown、解释或 SQL。
            """
        ).strip()

        return [
            LLMMessage(role="system", content=_QUERY_PLAN_ACTOR_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]


_QUERY_PLAN_ACTOR_SYSTEM_PROMPT = dedent(
    """
    你是证券客户营销场景的 QueryPlanActor，负责把自然语言问题转换为标准 QueryPlan。
    目标是生成后续 SQL agent 可以执行的结构化计划，但你自己不能生成 SQL。

    必须遵守：
    1. 只输出 JSON object，字段必须符合 QueryPlan schema。
    2. 优先忠实保留用户明示条件；不要替用户补未给出的阈值、时间、产品范围。
    3. 如果关键业务口径不明确，plan_status 必须是 needs_clarification，并给出
       clarifications；不要用 assumptions 偷偷猜口径。
    4. 如果规则版草稿已经合理，可以在它基础上补全字段；如果草稿误解了用户，要修正。
    5. metadata_ref 只能引用已知或草稿中出现的指标、字段、表；不确定时留空或要求澄清。
    6. output.limit 必须为正数且不超过 safety.max_rows；safety.readonly 必须为 true。

    正例：
    用户问“查询近三个月交易次数超过3次且当前资产大于50万的客户列表”。
    好的计划关键字段示例：
    {
      "plan_status": "ready",
      "intent": "customer_segmentation",
      "subject": {"name": "客户", "entity_type": "customer", "is_resolved": true},
      "filters": [
        {
          "term": "交易次数",
          "operator": ">",
          "value": {"raw": 3, "normalized": 3, "value_type": "number"},
          "metric_code": "trade_count_3m",
          "source": "user",
          "is_resolved": true
        },
        {
          "term": "当前资产",
          "operator": ">",
          "value": {"raw": "50万", "normalized": 500000, "value_type": "number"},
          "metric_code": "current_total_asset",
          "source": "user",
          "is_resolved": true
        }
      ],
      "grain": {"level": "customer", "keys": ["customer_id"], "is_resolved": true}
    }

    反例：
    用户问“找出高净值客户”。
    错误做法是直接假设“当前资产大于100万”并输出 ready。
    正确做法是 plan_status=needs_clarification，询问高净值客户的资产门槛。
    """
).strip()
