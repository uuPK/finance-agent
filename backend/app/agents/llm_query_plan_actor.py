import json
from dataclasses import dataclass
from textwrap import dedent
from typing import Any, Literal

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
        metadata_context: dict[str, Any] | None = None,
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
                messages=self._build_messages(
                    question,
                    previous_plan,
                    critic_feedback,
                    metadata_context=metadata_context,
                ),
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
        metadata_context: dict[str, Any] | None = None,
    ) -> list[LLMMessage]:
        schema = json.dumps(QueryPlan.model_json_schema(), ensure_ascii=False)
        metadata_json = json.dumps(
            self._metadata_summary(metadata_context or {}),
            ensure_ascii=False,
            indent=2,
        )
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

                当前任务模式：根据 critic 反馈修复上一版计划。
                修复要求：
                - 优先修复 failed feedback 中指出的字段、粒度、口径或安全问题。
                - 不要删除用户明示条件。
                - 不要为了通过审核而把明确条件改成澄清问题。
                - 如果 critic 指出业务口径被擅自猜测，应改为 needs_clarification。
                """
            )

        user_prompt = dedent(
            f"""
            用户问题：
            {question}
            {repair_context}

            Retrieved metadata context：
            {metadata_json}

            元数据使用要求：
            - metadata context 是已召回的业务证据，只能把其中存在的指标、业务词、表或字段写入 metadata_ref。
            - 如果用户使用了模糊业务词，而 metadata context 未给出明确口径，应返回 needs_clarification。
            - 如果 business_terms 中 clarification_required=true，除非用户已经给出口径，否则应返回 needs_clarification。
            - 不要编造 metadata context 中不存在的 metric_code、field_code、table、column 或 join_path。

            QueryPlan JSON Schema：
            {schema}

            输出要求：
            - 只输出一个合法 JSON object。
            - 不要输出 Markdown、解释、SQL、注释或额外文本。
            - JSON 必须能被 QueryPlan schema 校验通过。
            """
        ).strip()

        return [
            LLMMessage(role="system", content=_QUERY_PLAN_ACTOR_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]

    def _metadata_summary(self, metadata_context: dict[str, Any]) -> dict[str, Any]:
        retrieval = metadata_context.get("retrieval")
        tables = metadata_context.get("tables")
        metrics = metadata_context.get("metrics")
        business_terms = metadata_context.get("business_terms")
        examples = metadata_context.get("question_examples")
        return {
            "source": metadata_context.get("source"),
            "error": metadata_context.get("error"),
            "retrieval": retrieval if isinstance(retrieval, dict) else {},
            "table_allowlist": metadata_context.get("table_allowlist", []),
            "tables": self._compact_items(tables, ("name", "display_name", "domain", "grain")),
            "metrics": self._compact_items(
                metrics,
                ("metric_code", "metric_name", "description", "grain", "required_filters"),
            ),
            "business_terms": self._compact_items(
                business_terms,
                ("term", "definition", "synonyms", "default_plan_fragment", "clarification_required"),
            ),
            "question_examples": self._compact_items(
                examples, ("question", "difficulty", "tags")
            ),
        }

    def _compact_items(
        self, value: object, keys: tuple[str, ...], limit: int = 8
    ) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        compacted: list[dict[str, Any]] = []
        for item in value[:limit]:
            if not isinstance(item, dict):
                continue
            compacted.append({key: item.get(key) for key in keys if key in item})
        return compacted


_QUERY_PLAN_ACTOR_SYSTEM_PROMPT = dedent(
    """
    你是证券客户营销场景的 QueryPlanActor。你的任务是把用户自然语言问题转换成
    后续 SQL agent 可以消费的标准 QueryPlan。你只负责规划，不生成 SQL，不执行查询。

    输出契约：
    1. 只输出一个 JSON object，且必须符合 QueryPlan schema。
    2. 必须输出完整 QueryPlan，而不是片段。schema 中有默认值的字段也应尽量显式给出。
    3. plan_status 只能根据需求确定性选择：
       - ready：主体、指标/过滤口径、时间、粒度足够明确，可以进入 SQL 生成。
       - needs_clarification：关键业务词或范围不明确，必须先问用户。
       - invalid：请求越权、非问数、要求写库、或明显无法支持。
       - draft：只在极少数中间态使用；面向接口返回时尽量不用 draft。
    4. confidence 反映你对计划可执行性的把握：
       - ready 通常 >= 0.75。
       - needs_clarification 通常 0.45-0.70。
       - invalid 通常 <= 0.40。

    生成策略：
    1. 忠实保留用户明示的主体、指标、阈值、比较符、时间窗口、分组粒度和输出形式。
    2. 不要替用户补未给出的阈值、时间、产品范围、客户范围或业务口径。
    3. “高净值客户”“活跃客户”“沉默客户”“重点客户”“潜力客户”等业务词，
       如果没有明确口径，必须进入 needs_clarification。
    4. QueryPlan 是业务规划层，不直接绑定物理 SQL 字段；真实表、字段、指标公式和 join 路径
       会由 SQLActor 的 schema context 负责映射与校验。
    5. 用户消息会提供 Retrieved metadata context；metadata_ref 只能引用其中召回到的业务指标、
       业务词、表或字段。不确定时不要编造
       table、column、metric_id 或 join_path。
    6. metric_code / field_code 是业务规划代码，不等同于真实数据库字段名。
    7. output.limit 必须为正数且不超过 safety.max_rows。
    8. safety.readonly 必须为 true，allow_sensitive_fields 默认为 false。
    9. 不得输出客户手机号、身份证、银行卡号等敏感字段；如用户要求，应标记 invalid 或澄清脱敏方式。

    澄清问题策略：
    - 每个 clarification 必须包含 field、question、reason。
    - options 应给 2-4 个业务上合理的候选口径。
    - 有澄清问题时 plan_status 必须是 needs_clarification。
    - needs_clarification 下可以保留已经明确的主体、时间和输出偏好，但不要生成假定过滤条件。

    修复策略：
    - 如果用户消息中包含上一版计划和 critic 反馈，优先修复 critic 指出的失败项。
    - 修复时尽量最小改动，不要改掉已经正确的用户条件。
    - 如果失败原因是“擅自猜业务定义”，正确修复通常是 needs_clarification。

    正例 1：
    用户问“查询近三个月交易次数超过3次且当前资产大于50万的客户列表”。
    好的计划关键字段示例，实际输出必须是完整 QueryPlan：
    {
      "plan_status": "ready",
      "intent": "customer_segmentation",
      "subject": {"name": "客户", "entity_type": "customer", "is_resolved": true},
      "time_range": {"label": "近三个月", "relative": "last_3_months", "granularity": "day"},
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

    反例 1：
    用户问“找出高净值客户”。
    错误做法是直接假设“当前资产大于100万”并输出 ready。
    正确做法是 plan_status=needs_clarification，询问高净值客户的资产门槛。

    正例 2：
    用户问“按服务经理统计近30天触达客户数”。
    正确做法是 subject=服务经理或客户营销触达，grain.level=manager，
    metrics 包含触达客户数，time_range=近30天，output.format=summary 或 table。

    反例 2：
    用户问“把筛选出的客户手机号导出来”。
    错误做法是 output.columns 包含手机号并 ready。
    正确做法是 invalid 或 needs_clarification，说明敏感字段需要脱敏或授权策略。
    """
).strip()
