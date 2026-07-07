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
from app.services.sql_executor import SQLExecutionResult


ResultCriticStatus = Literal["reviewed", "failed", "skipped"]


@dataclass(slots=True)
class LLMResultCriticResult:
    status: ResultCriticStatus
    decision: ReviewDecision | None = None
    llm_error: str | None = None
    llm_raw_response: str | None = None
    llm_model: str | None = None
    llm_provider: str | None = None


class LLMResultCritic:
    """Review whether SQL execution results satisfy the user question and QueryPlan."""

    def __init__(self, llm_service: SupportsLLMComplete | None) -> None:
        self.llm_service = llm_service

    async def review(
        self,
        question: str,
        query_plan: QueryPlan,
        sql_draft: SQLDraft,
        execution_result: SQLExecutionResult,
        hard_checks: list[ReviewDecision],
        metadata_context: dict[str, Any],
        preview_rows: int,
    ) -> LLMResultCriticResult:
        if self.llm_service is None:
            return LLMResultCriticResult(
                status="failed",
                llm_error="LLM service is required for result semantic review.",
            )

        try:
            response = await self.llm_service.complete(
                messages=self._build_messages(
                    question=question,
                    query_plan=query_plan,
                    sql_draft=sql_draft,
                    execution_result=execution_result,
                    hard_checks=hard_checks,
                    metadata_context=metadata_context,
                    preview_rows=preview_rows,
                ),
                temperature=0.0,
                max_tokens=1800,
                response_format={"type": "json_object"},
            )
            data = extract_json_object(response.content)
            decision = ReviewDecision.model_validate(data)
            if decision.stage != "result_review":
                decision = decision.model_copy(update={"stage": "result_review"})
            return LLMResultCriticResult(
                status="reviewed",
                decision=decision,
                llm_raw_response=response.content,
                llm_model=response.model,
                llm_provider=response.provider,
            )
        except Exception as exc:
            return LLMResultCriticResult(
                status="failed",
                llm_error=f"{type(exc).__name__}: {exc}",
            )

    def _build_messages(
        self,
        question: str,
        query_plan: QueryPlan,
        sql_draft: SQLDraft,
        execution_result: SQLExecutionResult,
        hard_checks: list[ReviewDecision],
        metadata_context: dict[str, Any],
        preview_rows: int,
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
        result_summary = {
            "status": execution_result.status,
            "columns": execution_result.columns,
            "row_count": execution_result.row_count,
            "truncated": execution_result.truncated,
            "elapsed_ms": execution_result.elapsed_ms,
            "error_type": execution_result.error_type,
            "error_message": execution_result.error_message,
            "preview_rows_limit": preview_rows,
            "preview_rows": execution_result.rows[:preview_rows],
        }
        result_summary_json = json.dumps(result_summary, ensure_ascii=False, indent=2)
        metadata_summary_json = json.dumps(
            self._metadata_summary(metadata_context),
            ensure_ascii=False,
            indent=2,
        )

        user_prompt = dedent(
            f"""
            用户问题：
            {question}

            Approved QueryPlan：
            {query_plan_json}

            Executed SQLDraft：
            {sql_draft_json}

            Result hard checks：
            {hard_checks_json}

            SQL execution result summary，注意这里只包含受控预览行：
            {result_summary_json}

            Metadata summary：
            {metadata_summary_json}

            ReviewDecision JSON Schema：
            {review_schema}

            输出要求：
            - 只输出一个合法 JSON object。
            - JSON 必须能被 ReviewDecision schema 校验通过。
            - stage 必须是 result_review。
            - 不要输出 Markdown、解释、SQL、注释或额外文本。
            """
        ).strip()

        return [
            LLMMessage(role="system", content=_RESULT_CRITIC_SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_prompt),
        ]

    def _metadata_summary(self, metadata_context: dict[str, Any]) -> dict[str, Any]:
        metrics = metadata_context.get("metrics")
        metric_codes: list[str] = []
        if isinstance(metrics, list):
            metric_codes = [
                metric["metric_code"]
                for metric in metrics
                if isinstance(metric, dict) and isinstance(metric.get("metric_code"), str)
            ]
        return {
            "source": metadata_context.get("source"),
            "table_count": metadata_context.get("table_count", 0),
            "metric_count": metadata_context.get("metric_count", 0),
            "table_allowlist": metadata_context.get("table_allowlist", []),
            "metric_codes": metric_codes,
            "sensitive_columns": metadata_context.get("sensitive_columns", []),
        }


_RESULT_CRITIC_SYSTEM_PROMPT = dedent(
    """
    你是证券客户营销问数系统的 ResultCritic。你的任务是审核 SQL 执行结果是否足以
    支撑用户问题和已通过审核的 QueryPlan。
    你只审核，不生成 SQL，不重写完整答案，不要求查看全量结果。

    审核边界：
    1. Result hard checks 是安全 veto。若 hard check failed，你必须 passed=false。
    2. 你只能使用用户问题、QueryPlan、SQLDraft、执行统计、字段名、行数和预览行。
    3. 预览行不是全量数据。不要因为没有看到所有行就要求全量返回。
    4. 你关注结果是否能回答问题：字段、粒度、指标、过滤语义、空结果合理性。
    5. 你不能编造业务原因、营销建议、隐藏字段或未提供的数值。
    6. 如果结果明显无法支撑用户请求，必须失败，并给出可执行 repair_hint。

    必查项：
    - SQL 是否执行成功，且 hard checks 是否全部通过。
    - Result columns 是否能支撑 QueryPlan.output.columns 和用户要求。
    - Result grain 是否符合 QueryPlan.grain，例如客户列表不能只返回汇总数。
    - Result row_count 是否与列表、TopN、汇总等输出目标一致。
    - Result preview 是否显示关键字段的非空或合理值。
    - 空结果是否可能是严格过滤导致；如果用户明确要名单但 row_count=0，应提示可能需要放宽条件。
    - 是否暴露敏感字段或疑似个人身份信息。

    评分和 passed 规则：
    - 90-100：结果字段、粒度和执行状态都能支撑问题，passed=true。
    - 75-89：轻微展示问题但不影响用户理解，passed=true。
    - 50-74：结果缺少关键字段、粒度可疑、空结果难以解释，passed=false。
    - 0-49：执行失败、敏感泄漏、完全答非所问或结果不能支撑问题，passed=false。

    失败输出要求：
    - error_type 必须简短稳定，例如 wrong_result_grain、wrong_result_columns、
      empty_result_unexpected、result_critic_failed、answer_not_supported。
    - evidence 必须引用具体字段、行数、QueryPlan 粒度、SQL 或 hard check。
    - repair_hint 必须可直接交给 SQLActor 修复，说明应调整 SELECT、WHERE、GROUP BY、
      JOIN、LIMIT 或输出字段中的哪一部分。

    正例：
    用户问“查询近三个月交易次数超过3次且当前资产大于50万的客户列表”。
    QueryPlan grain=customer，结果字段包含 customer_no、total_asset、trade_count_90d，
    row_count=90，hard checks 全部通过。
    应输出：
    {
      "passed": true,
      "score": 94,
      "stage": "result_review",
      "reason": "结果为客户粒度，字段覆盖客户编号、当前资产和近90天交易次数，可以支撑用户问题。",
      "evidence": ["grain=customer", "columns: customer_no,total_asset,trade_count_90d", "row_count=90"],
      "repair_hint": null,
      "clarification_questions": [],
      "confidence": 0.9
    }

    反例：
    用户要求客户列表，QueryPlan grain=customer，但结果只返回 total_count，没有 customer_id
    或 customer_no。
    应输出：
    {
      "passed": false,
      "score": 45,
      "stage": "result_review",
      "error_type": "wrong_result_grain",
      "reason": "用户要求客户列表，但结果只有汇总数量，不能支持客户明细输出。",
      "evidence": ["QueryPlan grain=customer", "Result columns: total_count"],
      "repair_hint": "重新生成 SQL，返回客户级标识字段和所需指标，而不是只返回汇总数量。",
      "clarification_questions": [],
      "confidence": 0.92
    }

    输出必须符合 ReviewDecision schema，stage 必须是 result_review。
    """
).strip()
