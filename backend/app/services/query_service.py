from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from app.agents.answer_actor import AnswerActor, AnswerRenderResult
from app.agents.llm_plan_critic import LLMPlanCritic, LLMPlanCriticResult
from app.agents.llm_query_plan_actor import LLMQueryPlanActor, QueryPlanBuildResult
from app.agents.llm_result_critic import LLMResultCritic, LLMResultCriticResult
from app.agents.llm_sql_actor import LLMSQLActor, SQLBuildResult
from app.agents.llm_sql_critic import LLMSQLCritic, LLMSQLCriticResult
from app.agents.plan_reviewer import QueryPlanHardValidator
from app.agents.query_plan_actor import RuleBasedQueryPlanActor
from app.core.config import get_settings
from app.guardrails.result_validator import ResultHardValidator, ResultValidationResult
from app.guardrails.sql_guardrail import GuardrailFinding, SQLGuardrail
from app.llm.protocols import SupportsLLMComplete
from app.metadata.schema_context import SchemaContextProvider
from app.schemas.query import AgentStep, GuardrailCheck, QueryRequest, QueryResponse
from app.schemas.query_plan import QueryPlan
from app.schemas.review import ReviewBundle, ReviewDecision
from app.schemas.sql import SQLDraft
from app.services.audit_logger import QueryAuditLogger
from app.services.sql_executor import SQLExecutionResult, SQLExecutor

EventSink = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(slots=True)
class SQLLoopResult:
    sql: str | None
    passed: bool
    build_results: list[SQLBuildResult]
    review_bundle: ReviewBundle
    hard_review_passed: bool
    critic_result: LLMSQLCriticResult
    review_history: list[dict[str, object]]
    repair_count: int
    metadata_context: dict[str, object]
    execution_result: SQLExecutionResult | None = None
    result_hard_validation: ResultValidationResult | None = None
    result_validation: ResultValidationResult | None = None
    result_critic_result: LLMResultCriticResult | None = None
    execution_history: list[dict[str, object]] | None = None
    failure_reason: str | None = None


class QueryService:
    def __init__(
        self,
        llm_service: SupportsLLMComplete | None = None,
        enable_llm: bool = True,
        max_repair_attempts: int = 2,
        schema_context_provider: SchemaContextProvider | None = None,
        sql_executor: SQLExecutor | None = None,
        result_validator: ResultHardValidator | None = None,
        audit_logger: QueryAuditLogger | None = None,
        result_preview_rows: int | None = None,
        event_sink: EventSink | None = None,
        event_attempt: int = 0,
    ) -> None:
        self.settings = get_settings()
        self.rule_based_actor = RuleBasedQueryPlanActor()
        self.plan_validator = QueryPlanHardValidator()
        self.llm_unavailable_reason: str | None = None
        self.max_repair_attempts = max(0, max_repair_attempts)

        resolved_llm_service = llm_service
        if resolved_llm_service is None and enable_llm:
            (
                resolved_llm_service,
                self.llm_unavailable_reason,
            ) = self._build_default_llm_service()
        elif not enable_llm:
            self.llm_unavailable_reason = "LLM is disabled for this QueryService instance."
        self.llm_enabled = resolved_llm_service is not None

        self.query_plan_actor = LLMQueryPlanActor(
            llm_service=resolved_llm_service,
            fallback_actor=self.rule_based_actor,
        )
        self.plan_critic = LLMPlanCritic(llm_service=resolved_llm_service)
        self.sql_actor = LLMSQLActor(llm_service=resolved_llm_service)
        self.sql_critic = LLMSQLCritic(llm_service=resolved_llm_service)
        self.result_critic = LLMResultCritic(llm_service=resolved_llm_service)
        self.answer_actor = AnswerActor()
        self.schema_context_provider = schema_context_provider or SchemaContextProvider()
        self.sql_executor = sql_executor or SQLExecutor()
        self.result_validator = result_validator
        self.audit_logger = audit_logger or QueryAuditLogger()
        self.event_sink = event_sink
        self.event_attempt = max(0, event_attempt)
        self.result_preview_rows = max(1, result_preview_rows or self.settings.result_preview_rows)
        self.default_sensitive_columns = {
            "phone",
            "mobile",
            "mobile_phone",
            "id_no",
            "id_number",
            "cert_no",
            "bank_account",
            "address",
        }

    async def run(
        self,
        request: QueryRequest,
        *,
        query_id: UUID | None = None,
        start_audit: bool = True,
        previous_plan: QueryPlan | None = None,
    ) -> QueryResponse:
        started_at = perf_counter()
        query_id = query_id or uuid4()
        if start_audit:
            self.audit_logger.start_query_run(
                query_id=query_id,
                question=request.question,
                user_id=request.user_id,
            )

        await self._emit(
            "receive_question",
            "passed",
            "已接收业务问题",
            {"question": request.question},
        )

        await self._emit("retrieve_metadata", "running", "正在检索相关元数据")
        metadata_context = self._load_metadata_context(request.question)
        await self._emit(
            "retrieve_metadata",
            "passed" if metadata_context.get("source") == "database" else "failed",
            "已完成元数据检索",
            self._metadata_context_summary(metadata_context),
        )
        await self._emit("build_query_plan", "running", "正在生成结构化查询计划")
        build_result = await self.query_plan_actor.build(
            request.question,
            fallback_plan=previous_plan,
            previous_plan=previous_plan,
            metadata_context=metadata_context,
        )
        deterministic_plan = self.rule_based_actor.build(request.question)
        if (
            previous_plan is None
            and deterministic_plan.plan_status == "needs_clarification"
            and deterministic_plan.clarifications
            and build_result.plan.plan_status == "ready"
            and not build_result.plan.metrics
        ):
            build_result = QueryPlanBuildResult(
                plan=deterministic_plan,
                source="rule_fallback",
                repair_attempt=build_result.repair_attempt,
                llm_error=(
                    "LLM plan omitted the metric required to resolve an ambiguous business term; "
                    "deterministic clarification policy applied."
                ),
                llm_model=build_result.llm_model,
                llm_provider=build_result.llm_provider,
            )
        query_plan = build_result.plan
        build_results = [build_result]
        await self._emit(
            "build_query_plan",
            "passed",
            "查询计划已生成",
            {
                "query_plan": query_plan.model_dump(mode="json", exclude_none=True),
                **self._build_actor_details(build_result, build_results),
            },
        )
        metadata_context = self._load_metadata_context(request.question, query_plan)
        review_bundle, hard_review_passed, critic_result = await self._review_query_plan(
            query_plan, metadata_context, attempt=0
        )
        review_history = [
            self._build_review_details(
                build_result.repair_attempt,
                review_bundle,
                hard_review_passed,
                critic_result,
            )
        ]

        repair_count = 0
        while self._should_repair(query_plan, review_bundle, repair_count):
            repair_feedback = self._failed_review_feedback(review_bundle)
            repair_count += 1
            await self._emit(
                "repair_query_plan",
                "running",
                f"正在进行第 {repair_count} 次查询计划修复",
                {"feedback": [item.model_dump(mode="json") for item in repair_feedback]},
                attempt=repair_count,
            )
            build_result = await self.query_plan_actor.build(
                request.question,
                fallback_plan=query_plan,
                previous_plan=query_plan,
                critic_feedback=repair_feedback,
                metadata_context=metadata_context,
                repair_attempt=repair_count,
            )
            build_results.append(build_result)

            await self._emit(
                "repair_query_plan",
                "passed" if build_result.source == "llm" else "failed",
                f"第 {repair_count} 次查询计划修复已完成",
                {
                    "query_plan": build_result.plan.model_dump(mode="json", exclude_none=True),
                    "actor_source": build_result.source,
                    "llm_error": build_result.llm_error,
                },
                attempt=repair_count,
            )

            if build_result.source != "llm":
                break

            query_plan = build_result.plan
            metadata_context = self._load_metadata_context(request.question, query_plan)
            review_bundle, hard_review_passed, critic_result = await self._review_query_plan(
                query_plan, metadata_context, attempt=repair_count
            )
            review_history.append(
                self._build_review_details(
                    build_result.repair_attempt,
                    review_bundle,
                    hard_review_passed,
                    critic_result,
                )
            )

        review_passed = review_bundle.passed
        sql_loop_result: SQLLoopResult | None = None
        answer_result: AnswerRenderResult | None = None

        if query_plan.plan_status == "invalid":
            status = "failed"
            answer = "The request is invalid for the current QueryPlan safety policy."
        elif not review_passed:
            status = "failed"
            answer = "QueryPlan failed review and needs repair before SQL generation."
        elif query_plan.plan_status == "needs_clarification":
            status = "needs_clarification"
            answer = "当前问题需要进一步明确后才能生成可靠查询。"
        else:
            sql_loop_result = await self._run_sql_loop(query_id, request.question, query_plan)
            if sql_loop_result.passed:
                if sql_loop_result.execution_result is None:
                    status = "failed"
                    answer = "SQL execution result is unavailable after validation."
                else:
                    status = "completed"
                    answer_result = self.answer_actor.render(
                        question=request.question,
                        query_plan=query_plan,
                        execution_result=sql_loop_result.execution_result,
                        preview_rows=self._response_preview_rows(sql_loop_result.execution_result),
                    )
                    answer = answer_result.answer
                    await self._emit(
                        "render_answer",
                        "passed",
                        "已根据查询结果生成回答",
                        {
                            "answer": answer,
                            "result_preview": self._response_preview_rows(
                                sql_loop_result.execution_result
                            ),
                        },
                    )
            else:
                status = "failed"
                answer = sql_loop_result.failure_reason or (
                    "SQL generation failed review before execution."
                )

        sql_checks = (
            [*sql_loop_result.review_bundle.hard_checks, *sql_loop_result.review_bundle.llm_checks]
            if sql_loop_result is not None
            else []
        )
        result_checks = (
            sql_loop_result.result_validation.checks
            if sql_loop_result is not None and sql_loop_result.result_validation is not None
            else []
        )
        sql_steps = self._build_sql_steps(sql_loop_result) if sql_loop_result is not None else []
        sql = sql_loop_result.sql if sql_loop_result and sql_loop_result.passed else None
        result_preview = (
            self._response_preview_rows(sql_loop_result.execution_result)
            if sql_loop_result
            and sql_loop_result.passed
            and sql_loop_result.execution_result is not None
            else []
        )
        total_retry_count = repair_count + (
            sql_loop_result.repair_count if sql_loop_result is not None else 0
        )

        elapsed_ms = int((perf_counter() - started_at) * 1000)
        all_checks = [
            *review_bundle.hard_checks,
            *review_bundle.llm_checks,
            *sql_checks,
            *result_checks,
        ]

        response = QueryResponse(
            query_id=query_id,
            status=status,
            answer=answer,
            query_plan=query_plan,
            sql=sql,
            result_preview=result_preview,
            guardrail_checks=self._to_guardrail_checks(all_checks),
            steps=[
                AgentStep(
                    name="receive_question",
                    status="passed",
                    summary="Received user question.",
                    details={"question": request.question},
                ),
                AgentStep(
                    name="build_query_plan",
                    status="passed",
                    summary="Built QueryPlan with LLM actor or deterministic fallback.",
                    details=self._build_actor_details(build_result, build_results),
                ),
                self._build_repair_step(repair_count, build_results, review_passed),
                AgentStep(
                    name="query_plan_hard_review",
                    status="passed" if hard_review_passed else "failed",
                    summary="Ran deterministic QueryPlan hard checks.",
                    details={
                        "checks": [check.model_dump() for check in review_bundle.hard_checks],
                        "review_history": review_history,
                    },
                ),
                self._build_critic_step(critic_result),
                *sql_steps,
                *(
                    [self._build_answer_step(answer_result, status)]
                    if sql_loop_result is not None
                    else []
                ),
            ],
            retry_count=total_retry_count,
            elapsed_ms=elapsed_ms,
        )
        failed_check = next((check for check in all_checks if not check.passed), None)
        self.audit_logger.finish_query_run(
            query_id=query_id,
            status=status,
            final_answer=answer,
            final_sql=sql,
            retry_count=total_retry_count,
            elapsed_ms=elapsed_ms,
            error_type=failed_check.error_type if failed_check else None,
            error_message=failed_check.reason if failed_check else None,
        )
        return response

    def _build_default_llm_service(
        self,
    ) -> tuple[SupportsLLMComplete | None, str | None]:
        try:
            from app.services.llm_service import LLMService

            service = LLMService()
            status = service.status()
            if not status["api_key_configured"]:
                return None, "LLM API key is not configured."
            return service, None
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    async def _review_query_plan(
        self,
        query_plan: QueryPlan,
        metadata_context: dict[str, object] | None = None,
        attempt: int = 0,
    ) -> tuple[ReviewBundle, bool, LLMPlanCriticResult]:
        await self._emit(
            "query_plan_hard_review",
            "running",
            "正在检查查询计划结构与安全约束",
            attempt=attempt,
        )
        review_bundle = self.plan_validator.review(query_plan)
        hard_review_passed = all(check.passed for check in review_bundle.hard_checks)
        await self._emit(
            "query_plan_hard_review",
            "passed" if hard_review_passed else "failed",
            "查询计划硬规则检查已完成",
            {"checks": [check.model_dump(mode="json") for check in review_bundle.hard_checks]},
            attempt=attempt,
        )

        critic_result = LLMPlanCriticResult(
            status="skipped",
            llm_error="Hard review failed; semantic critic skipped.",
        )
        if query_plan.plan_status == "invalid":
            critic_result = LLMPlanCriticResult(
                status="skipped",
                llm_error="Plan status is invalid; semantic critic skipped.",
            )
        elif hard_review_passed:
            await self._emit(
                "query_plan_llm_review",
                "running",
                "正在核对查询计划是否完整表达业务意图",
                attempt=attempt,
            )
            critic_result = await self.plan_critic.review(
                query_plan,
                review_bundle.hard_checks,
                metadata_context=metadata_context,
            )
            if critic_result.decision is not None:
                review_bundle.llm_checks.append(critic_result.decision)

        critic_status = (
            "passed"
            if critic_result.decision is not None and critic_result.decision.passed
            else "skipped"
            if critic_result.status == "skipped"
            else "failed"
        )
        await self._emit(
            "query_plan_llm_review",
            critic_status,
            "查询计划语义审核已完成",
            {
                "decision": critic_result.decision.model_dump(mode="json")
                if critic_result.decision is not None
                else None,
                "llm_error": critic_result.llm_error,
                "llm_model": critic_result.llm_model,
                "llm_provider": critic_result.llm_provider,
            },
            attempt=attempt,
        )

        return review_bundle, hard_review_passed, critic_result

    async def _emit(
        self,
        stage: str,
        status: str,
        summary: str,
        output: dict[str, Any] | None = None,
        *,
        attempt: int | None = None,
        event_type: str | None = None,
    ) -> None:
        if self.event_sink is None:
            return
        resolved_attempt = self.event_attempt + (attempt or 0)
        resolved_type = event_type
        if resolved_type is None:
            resolved_type = (
                "stage.started"
                if status == "running"
                else "stage.failed"
                if status == "failed"
                else "stage.completed"
            )
        await self.event_sink(
            {
                "type": resolved_type,
                "stage": stage,
                "status": status,
                "attempt": resolved_attempt,
                "summary": summary,
                "output": output or {},
            }
        )

    def _should_repair(
        self,
        query_plan: QueryPlan,
        review_bundle: ReviewBundle,
        repair_count: int,
    ) -> bool:
        if review_bundle.passed:
            return False
        if repair_count >= self.max_repair_attempts:
            return False
        if not self.llm_enabled:
            return False
        if query_plan.plan_status == "invalid":
            return False
        if getattr(query_plan, "plan_status", None) == "needs_clarification":
            return bool(self._failed_review_feedback(review_bundle))
        return True

    def _failed_review_feedback(self, review_bundle: ReviewBundle) -> list[ReviewDecision]:
        return [
            check
            for check in [*review_bundle.hard_checks, *review_bundle.llm_checks]
            if not check.passed
        ]

    async def _run_sql_loop(
        self, query_id: UUID, question: str, query_plan: QueryPlan
    ) -> SQLLoopResult:
        await self._emit("load_schema_context", "running", "正在加载 SQL 生成所需的数据结构")
        metadata_context = self._load_metadata_context(question, query_plan)
        await self._emit(
            "load_schema_context",
            "passed" if metadata_context.get("source") == "database" else "failed",
            "SQL 数据结构上下文已加载",
            self._metadata_context_summary(metadata_context),
        )
        await self._emit("generate_sql", "running", "正在根据已审核的查询计划生成 SQL")
        build_result = await self.sql_actor.build(
            question=question,
            query_plan=query_plan,
            metadata_context=metadata_context,
        )
        build_results = [build_result]
        await self._emit(
            "generate_sql",
            "passed" if build_result.draft is not None else "failed",
            "SQL 生成已完成" if build_result.draft is not None else "SQL 生成失败",
            {
                "sql": build_result.draft.sql if build_result.draft else None,
                "tables": build_result.draft.tables if build_result.draft else [],
                "columns": build_result.draft.columns if build_result.draft else [],
                "assumptions": build_result.draft.assumptions if build_result.draft else [],
                "confidence": build_result.draft.confidence if build_result.draft else None,
                "llm_error": build_result.llm_error,
                "llm_model": build_result.llm_model,
                "llm_provider": build_result.llm_provider,
            },
        )

        if build_result.draft is None:
            review_bundle = ReviewBundle(
                hard_checks=[self._sql_actor_failure_decision(build_result)]
            )
            return SQLLoopResult(
                sql=None,
                passed=False,
                build_results=build_results,
                review_bundle=review_bundle,
                hard_review_passed=False,
                critic_result=LLMSQLCriticResult(
                    status="failed",
                    llm_error="SQL actor failed before semantic review.",
                ),
                review_history=[
                    self._build_sql_review_details(
                        build_result.repair_attempt,
                        review_bundle,
                        False,
                        None,
                    )
                ],
                repair_count=0,
                metadata_context=metadata_context,
                execution_history=[],
                failure_reason=build_result.llm_error or "SQL generation failed.",
            )

        repair_count = 0
        review_bundle = ReviewBundle()
        hard_review_passed = False
        critic_result = LLMSQLCriticResult(status="failed")
        review_history: list[dict[str, object]] = []
        execution_result: SQLExecutionResult | None = None
        result_hard_validation: ResultValidationResult | None = None
        result_validation: ResultValidationResult | None = None
        result_critic_result = LLMResultCriticResult(
            status="skipped",
            llm_error="Result review has not run.",
        )
        execution_history: list[dict[str, object]] = []

        while True:
            review_bundle, hard_review_passed, critic_result = await self._review_sql_draft(
                query_plan,
                build_result.draft,
                metadata_context,
                attempt=build_result.repair_attempt,
            )
            review_history.append(
                self._build_sql_review_details(
                    build_result.repair_attempt,
                    review_bundle,
                    hard_review_passed,
                    critic_result,
                )
            )

            execution_result = None
            result_hard_validation = None
            result_validation = None
            result_critic_result = LLMResultCriticResult(
                status="skipped",
                llm_error="Result review skipped before SQL execution.",
            )
            if review_bundle.passed and build_result.draft is not None:
                await self._emit(
                    "execute_sql",
                    "running",
                    "正在只读事务中执行已审核的 SQL",
                    {"sql": build_result.draft.sql},
                    attempt=build_result.repair_attempt,
                )
                execution_result = self.sql_executor.execute(build_result.draft.sql)
                execution_id = self.audit_logger.log_sql_execution(
                    query_id=query_id,
                    attempt=build_result.repair_attempt,
                    result=execution_result,
                )
                result_hard_validation = self._validate_execution_result(
                    query_plan=query_plan,
                    execution_result=execution_result,
                    metadata_context=metadata_context,
                )
                await self._emit(
                    "execute_sql",
                    "passed" if execution_result.status == "success" else "failed",
                    "SQL 执行已完成",
                    {
                        "status": execution_result.status,
                        "row_count": execution_result.row_count,
                        "columns": execution_result.columns,
                        "truncated": execution_result.truncated,
                        "elapsed_ms": execution_result.elapsed_ms,
                        "error_type": execution_result.error_type,
                        "error_message": execution_result.error_message,
                        "result_preview": execution_result.rows[: self.result_preview_rows],
                    },
                    attempt=build_result.repair_attempt,
                )
                await self._emit(
                    "result_hard_review",
                    "passed" if result_hard_validation.passed else "failed",
                    "查询结果硬规则检查已完成",
                    {
                        "score": result_hard_validation.score,
                        "checks": [
                            check.model_dump(mode="json") for check in result_hard_validation.checks
                        ],
                        "error_type": result_hard_validation.error_type,
                        "repair_hint": result_hard_validation.repair_hint,
                    },
                    attempt=build_result.repair_attempt,
                )
                await self._emit(
                    "result_llm_review",
                    "running" if result_hard_validation.passed else "skipped",
                    "正在核对查询结果与用户问题是否一致"
                    if result_hard_validation.passed
                    else "结果硬规则未通过，语义审核已跳过",
                    attempt=build_result.repair_attempt,
                )
                result_validation, result_critic_result = await self._review_result(
                    question=question,
                    query_plan=query_plan,
                    sql_draft=build_result.draft,
                    execution_result=execution_result,
                    hard_validation=result_hard_validation,
                    metadata_context=metadata_context,
                )
                result_critic_status = (
                    "passed"
                    if result_critic_result.decision is not None
                    and result_critic_result.decision.passed
                    else "skipped"
                    if result_critic_result.status == "skipped"
                    else "failed"
                )
                await self._emit(
                    "result_llm_review",
                    result_critic_status,
                    "查询结果语义审核已完成",
                    self._result_critic_log_payload(result_critic_result),
                    attempt=build_result.repair_attempt,
                )
                self.audit_logger.log_result_validation(
                    query_id=query_id,
                    execution_id=execution_id,
                    result=result_validation,
                    critic_review=self._result_critic_log_payload(result_critic_result),
                    hard_checks=result_hard_validation.checks,
                )
                execution_history.append(
                    self._build_execution_details(
                        build_result.repair_attempt,
                        execution_result,
                        result_hard_validation,
                        result_validation,
                        result_critic_result,
                        execution_id,
                    )
                )

            if not self._should_repair_sql_attempt(review_bundle, result_validation, repair_count):
                break

            repair_feedback = self._failed_sql_attempt_feedback(review_bundle, result_validation)
            previous_sql = build_result.draft.sql
            repair_count += 1
            await self._emit(
                "repair_sql",
                "running",
                f"正在进行第 {repair_count} 次 SQL 修复",
                {"feedback": [item.model_dump(mode="json") for item in repair_feedback]},
                attempt=repair_count,
            )
            build_result = await self.sql_actor.build(
                question=question,
                query_plan=query_plan,
                metadata_context=metadata_context,
                previous_sql=previous_sql,
                critic_feedback=repair_feedback,
                repair_attempt=repair_count,
            )
            build_results.append(build_result)
            await self._emit(
                "repair_sql",
                "passed" if build_result.draft is not None else "failed",
                f"第 {repair_count} 次 SQL 修复已完成",
                {
                    "sql": build_result.draft.sql if build_result.draft else None,
                    "llm_error": build_result.llm_error,
                    "llm_model": build_result.llm_model,
                    "llm_provider": build_result.llm_provider,
                },
                attempt=repair_count,
            )

            if build_result.draft is None:
                review_bundle = ReviewBundle(
                    hard_checks=[self._sql_actor_failure_decision(build_result)]
                )
                hard_review_passed = False
                critic_result = LLMSQLCriticResult(
                    status="failed",
                    llm_error="SQL actor failed during repair.",
                )
                review_history.append(
                    self._build_sql_review_details(
                        build_result.repair_attempt,
                        review_bundle,
                        hard_review_passed,
                        critic_result,
                    )
                )
                break

        passed = bool(review_bundle.passed and result_validation and result_validation.passed)
        sql = build_result.draft.sql if passed and build_result.draft is not None else None
        failure_reason = self._sql_loop_failure_reason(
            review_bundle, execution_result, result_validation
        )

        return SQLLoopResult(
            sql=sql,
            passed=passed,
            build_results=build_results,
            review_bundle=review_bundle,
            hard_review_passed=hard_review_passed,
            critic_result=critic_result,
            review_history=review_history,
            repair_count=repair_count,
            metadata_context=metadata_context,
            execution_result=execution_result,
            result_hard_validation=result_hard_validation,
            result_validation=result_validation,
            result_critic_result=result_critic_result,
            execution_history=execution_history,
            failure_reason=failure_reason,
        )

    def _load_metadata_context(
        self, question: str, query_plan: QueryPlan | None = None
    ) -> dict[str, object]:
        try:
            return self.schema_context_provider.load(
                query_plan=query_plan,
                question=question,
            )
        except TypeError as exc:
            if "question" not in str(exc):
                raise
            if query_plan is not None:
                return self.schema_context_provider.load(query_plan)
            return self.schema_context_provider.load()

    async def _review_sql_draft(
        self,
        query_plan: QueryPlan,
        sql_draft: SQLDraft,
        metadata_context: dict[str, object],
        attempt: int = 0,
    ) -> tuple[ReviewBundle, bool, LLMSQLCriticResult]:
        await self._emit(
            "sql_hard_review",
            "running",
            "正在检查 SQL 安全性、表字段和结果行数限制",
            attempt=attempt,
        )
        guardrail_findings = self._build_sql_guardrail(metadata_context).validate(sql_draft.sql)
        hard_checks = [
            self._guardrail_finding_to_review_decision(finding) for finding in guardrail_findings
        ]
        review_bundle = ReviewBundle(hard_checks=hard_checks)
        hard_review_passed = all(check.passed for check in hard_checks)
        await self._emit(
            "sql_hard_review",
            "passed" if hard_review_passed else "failed",
            "SQL 硬规则检查已完成",
            {"checks": [check.model_dump(mode="json") for check in hard_checks]},
            attempt=attempt,
        )

        critic_result = LLMSQLCriticResult(
            status="failed",
            llm_error="Hard SQL review failed; SQLCritic skipped.",
        )
        if hard_review_passed:
            await self._emit(
                "sql_llm_review",
                "running",
                "正在核对 SQL 是否完整实现查询计划",
                attempt=attempt,
            )
            critic_result = await self.sql_critic.review(
                query_plan=query_plan,
                sql_draft=sql_draft,
                hard_checks=hard_checks,
            )
            if critic_result.decision is not None:
                decision = self._enforce_sql_critic_confidence(critic_result.decision)
                review_bundle.llm_checks.append(decision)
            else:
                review_bundle.llm_checks.append(self._sql_critic_failure_decision(critic_result))

        critic_status = (
            "passed"
            if critic_result.decision is not None and critic_result.decision.passed
            else "skipped"
            if not hard_review_passed
            else "failed"
        )
        await self._emit(
            "sql_llm_review",
            critic_status,
            "SQL 语义审核已完成",
            {
                "decision": critic_result.decision.model_dump(mode="json")
                if critic_result.decision is not None
                else None,
                "llm_error": critic_result.llm_error,
                "llm_model": critic_result.llm_model,
                "llm_provider": critic_result.llm_provider,
            },
            attempt=attempt,
        )

        return review_bundle, hard_review_passed, critic_result

    def _validate_execution_result(
        self,
        query_plan: QueryPlan,
        execution_result: SQLExecutionResult,
        metadata_context: dict[str, object],
    ) -> ResultValidationResult:
        validator = self.result_validator or ResultHardValidator(
            max_result_rows=self.settings.max_result_rows,
            sensitive_columns=set(self._string_list(metadata_context.get("sensitive_columns"))),
        )
        return validator.validate(query_plan, execution_result)

    async def _review_result(
        self,
        question: str,
        query_plan: QueryPlan,
        sql_draft: SQLDraft,
        execution_result: SQLExecutionResult,
        hard_validation: ResultValidationResult,
        metadata_context: dict[str, object],
    ) -> tuple[ResultValidationResult, LLMResultCriticResult]:
        critic_result = LLMResultCriticResult(
            status="skipped",
            llm_error="Result hard validation failed; ResultCritic skipped.",
        )
        if hard_validation.passed:
            critic_result = await self.result_critic.review(
                question=question,
                query_plan=query_plan,
                sql_draft=sql_draft,
                execution_result=execution_result,
                hard_checks=hard_validation.checks,
                metadata_context=metadata_context,
                preview_rows=self.result_preview_rows,
            )
            return (
                self._merge_result_critic_decision(hard_validation, critic_result),
                critic_result,
            )
        return hard_validation, critic_result

    def _merge_result_critic_decision(
        self,
        hard_validation: ResultValidationResult,
        critic_result: LLMResultCriticResult,
    ) -> ResultValidationResult:
        if critic_result.decision is not None:
            decision = self._enforce_result_critic_confidence(critic_result.decision)
        else:
            decision = self._result_critic_failure_decision(critic_result)

        checks = [*hard_validation.checks, decision]
        failed_check = next((check for check in checks if not check.passed), None)
        score = int(sum(check.score for check in checks) / len(checks)) if checks else 0
        return ResultValidationResult(
            passed=failed_check is None,
            checks=checks,
            score=score,
            error_type=failed_check.error_type if failed_check else None,
            repair_hint=failed_check.repair_hint if failed_check else None,
        )

    def _result_critic_failure_decision(self, result: LLMResultCriticResult) -> ReviewDecision:
        return ReviewDecision(
            passed=False,
            score=0,
            stage="result_review",
            error_type="result_critic_failed",
            reason=result.llm_error or "ResultCritic did not return a valid decision.",
            evidence=["result_critic"],
            repair_hint="Check LLM configuration and retry result semantic review.",
            confidence=1.0,
        )

    def _enforce_result_critic_confidence(self, decision: ReviewDecision) -> ReviewDecision:
        if decision.passed and decision.confidence < 0.7:
            return decision.model_copy(
                update={
                    "passed": False,
                    "error_type": "low_result_critic_confidence",
                    "reason": (
                        "ResultCritic confidence is below the auto-pass threshold: "
                        f"{decision.confidence}."
                    ),
                    "repair_hint": "Regenerate SQL or request stronger metadata context.",
                }
            )
        return decision

    def _result_critic_log_payload(self, result: LLMResultCriticResult | None) -> dict[str, object]:
        if result is None:
            return {}
        return {
            "status": result.status,
            "decision": result.decision.model_dump(mode="json")
            if result.decision is not None
            else None,
            "llm_error": result.llm_error,
            "llm_model": result.llm_model,
            "llm_provider": result.llm_provider,
        }

    def _response_preview_rows(
        self, execution_result: SQLExecutionResult
    ) -> list[dict[str, object]]:
        return execution_result.rows[: self.result_preview_rows]

    def _build_answer_step(
        self, result: AnswerRenderResult | None, response_status: str
    ) -> AgentStep:
        if result is None:
            return AgentStep(
                name="render_answer",
                status="skipped" if response_status != "completed" else "failed",
                summary="Answer rendering was skipped because no reviewed result was available.",
                details={"renderer": "deterministic_result_renderer"},
            )
        return AgentStep(
            name="render_answer",
            status="passed",
            summary="Rendered final answer from reviewed database result.",
            details=result.to_dict(),
        )

    def _build_sql_guardrail(self, metadata_context: dict[str, object]) -> SQLGuardrail:
        table_allowlist = set(self._string_list(metadata_context.get("table_allowlist")))
        sensitive_columns = {
            *self.default_sensitive_columns,
            *self._string_list(metadata_context.get("sensitive_columns")),
        }
        allowed_columns_by_table = {
            table_name: set(self._string_list(columns))
            for table_name, columns in self._dict_value(
                metadata_context.get("allowed_columns_by_table")
            ).items()
        }
        return SQLGuardrail(
            allowed_tables=table_allowlist,
            allowed_columns_by_table=allowed_columns_by_table,
            sensitive_columns=sensitive_columns,
        )

    def _string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]

    def _dict_value(self, value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            return {}
        return {key: item for key, item in value.items() if isinstance(key, str)}

    def _should_repair_sql_attempt(
        self,
        review_bundle: ReviewBundle,
        result_validation: ResultValidationResult | None,
        repair_count: int,
    ) -> bool:
        if review_bundle.passed and result_validation is not None and result_validation.passed:
            return False
        if repair_count >= self.max_repair_attempts:
            return False
        if not self.llm_enabled:
            return False
        if not review_bundle.passed:
            return bool(self._failed_review_feedback(review_bundle))
        if result_validation is not None:
            return bool(self._failed_result_feedback(result_validation))
        return False

    def _failed_sql_attempt_feedback(
        self,
        review_bundle: ReviewBundle,
        result_validation: ResultValidationResult | None,
    ) -> list[ReviewDecision]:
        feedback = self._failed_review_feedback(review_bundle)
        if result_validation is not None:
            feedback.extend(self._failed_result_feedback(result_validation))
        return feedback

    def _failed_result_feedback(
        self, result_validation: ResultValidationResult
    ) -> list[ReviewDecision]:
        return [check for check in result_validation.checks if not check.passed]

    def _sql_loop_failure_reason(
        self,
        review_bundle: ReviewBundle,
        execution_result: SQLExecutionResult | None,
        result_validation: ResultValidationResult | None,
    ) -> str | None:
        if review_bundle.passed is False:
            return "SQL generation failed review before execution."
        if execution_result is not None and execution_result.status != "success":
            return execution_result.error_message or "SQL execution failed."
        if result_validation is not None and not result_validation.passed:
            return result_validation.repair_hint or "SQL result failed hard validation."
        return None

    def _guardrail_finding_to_review_decision(self, finding: GuardrailFinding) -> ReviewDecision:
        return ReviewDecision(
            passed=finding.passed,
            score=100 if finding.passed else 0,
            stage="sql_review",
            error_type=None if finding.passed else finding.name,
            reason=finding.message,
            evidence=[finding.name],
            repair_hint=None if finding.passed else self._sql_repair_hint(finding.name),
            confidence=1.0,
        )

    def _sql_actor_failure_decision(self, result: SQLBuildResult) -> ReviewDecision:
        return ReviewDecision(
            passed=False,
            score=0,
            stage="sql_review",
            error_type="sql_actor_failed",
            reason=result.llm_error or "SQL actor failed.",
            evidence=["sql_actor"],
            repair_hint="Check LLM configuration and retry SQL generation.",
            confidence=1.0,
        )

    def _sql_critic_failure_decision(self, result: LLMSQLCriticResult) -> ReviewDecision:
        return ReviewDecision(
            passed=False,
            score=0,
            stage="sql_review",
            error_type="sql_critic_failed",
            reason=result.llm_error or "SQLCritic did not return a valid decision.",
            evidence=["sql_critic"],
            repair_hint="Check LLM configuration and retry SQL semantic review.",
            confidence=1.0,
        )

    def _enforce_sql_critic_confidence(self, decision: ReviewDecision) -> ReviewDecision:
        if decision.passed and decision.confidence < 0.7:
            return decision.model_copy(
                update={
                    "passed": False,
                    "error_type": "low_critic_confidence",
                    "reason": (
                        "SQLCritic confidence is below the auto-pass threshold: "
                        f"{decision.confidence}."
                    ),
                    "repair_hint": "Regenerate SQL or request stronger metadata context.",
                }
            )
        return decision

    def _sql_repair_hint(self, error_type: str) -> str:
        hints = {
            "single_statement": "Return exactly one SELECT statement.",
            "select_only": "Regenerate SQL as a read-only SELECT query.",
            "forbidden_operations": "Remove all write or DDL operations.",
            "select_star": "Replace SELECT * with explicit output columns and aliases.",
            "table_whitelist": "Use only metadata-approved tables.",
            "column_whitelist": "Use only columns that exist in schema context.",
            "sensitive_columns": "Remove sensitive columns from SELECT and output.",
            "limit_required": "Add a LIMIT clause within the allowed max rows.",
            "limit_value": "Use a positive integer literal in LIMIT.",
            "limit_max_rows": "Lower LIMIT to the configured max rows.",
            "sql_parse": "Regenerate syntactically valid PostgreSQL SQL.",
        }
        return hints.get(error_type, "Regenerate SQL to satisfy hard guardrail checks.")

    def _build_sql_steps(self, result: SQLLoopResult) -> list[AgentStep]:
        latest_build = result.build_results[-1]
        return [
            AgentStep(
                name="load_schema_context",
                status="passed"
                if result.metadata_context.get("source") == "database"
                and result.metadata_context.get("table_count", 0)
                else "failed",
                summary="Loaded database schema context for SQL generation.",
                details=self._metadata_context_summary(result.metadata_context),
            ),
            AgentStep(
                name="generate_sql",
                status="passed" if latest_build.draft is not None else "failed",
                summary="Generated SQL with LLM SQL actor.",
                details=self._build_sql_actor_details(result),
            ),
            self._build_sql_repair_step(result),
            AgentStep(
                name="sql_hard_review",
                status="passed" if result.hard_review_passed else "failed",
                summary="Ran deterministic SQL hard guardrail checks.",
                details={
                    "checks": [check.model_dump() for check in result.review_bundle.hard_checks],
                    "review_history": result.review_history,
                },
            ),
            self._build_sql_critic_step(result.critic_result),
            self._build_sql_execution_step(result),
            self._build_result_validation_step(result),
            self._build_result_critic_step(result),
        ]

    def _build_sql_actor_details(self, result: SQLLoopResult) -> dict[str, object]:
        latest_build = result.build_results[-1]
        return {
            "actor_source": latest_build.source,
            "attempt_count": len(result.build_results),
            "repair_attempts": result.repair_count,
            "llm_error": latest_build.llm_error,
            "llm_model": latest_build.llm_model,
            "llm_provider": latest_build.llm_provider,
            "sql_available": latest_build.draft is not None,
            "assumptions": latest_build.draft.assumptions if latest_build.draft else [],
            "tables": latest_build.draft.tables if latest_build.draft else [],
            "columns": latest_build.draft.columns if latest_build.draft else [],
            "confidence": latest_build.draft.confidence if latest_build.draft else None,
            "metadata_context": self._metadata_context_summary(result.metadata_context),
            "attempts": [
                {
                    "repair_attempt": item.repair_attempt,
                    "actor_source": item.source,
                    "llm_error": item.llm_error,
                    "llm_model": item.llm_model,
                    "llm_provider": item.llm_provider,
                    "sql_available": item.draft is not None,
                }
                for item in result.build_results
            ],
        }

    def _metadata_context_summary(self, metadata_context: dict[str, object]) -> dict[str, object]:
        table_allowlist = self._string_list(metadata_context.get("table_allowlist"))
        metrics = metadata_context.get("metrics")
        metric_codes = []
        if isinstance(metrics, list):
            metric_codes = [
                metric["metric_code"]
                for metric in metrics
                if isinstance(metric, dict) and isinstance(metric.get("metric_code"), str)
            ]
        retrieval = metadata_context.get("retrieval")
        retrieval_summary: dict[str, object] = {}
        if isinstance(retrieval, dict):
            retrieval_summary = {
                "strategy": retrieval.get("strategy"),
                "confidence": retrieval.get("confidence"),
                "keywords": self._string_list(retrieval.get("keywords"))[:12],
                "business_terms": self._string_list(retrieval.get("business_terms")),
            }
        return {
            "source": metadata_context.get("source"),
            "error": metadata_context.get("error"),
            "table_count": metadata_context.get("table_count", 0),
            "metric_count": metadata_context.get("metric_count", 0),
            "tables": table_allowlist,
            "metrics": metric_codes,
            "retrieval": retrieval_summary,
        }

    def _build_sql_repair_step(self, result: SQLLoopResult) -> AgentStep:
        if result.repair_count == 0:
            return AgentStep(
                name="repair_sql",
                status="skipped",
                summary="No SQL repair was required.",
                details={"max_repair_attempts": self.max_repair_attempts},
            )

        return AgentStep(
            name="repair_sql",
            status="passed" if result.passed else "failed",
            summary="Repaired SQL with guardrail or critic feedback.",
            details={
                "repair_count": result.repair_count,
                "max_repair_attempts": self.max_repair_attempts,
                "attempt_sources": [item.source for item in result.build_results],
            },
        )

    def _build_sql_review_details(
        self,
        repair_attempt: int,
        review_bundle: ReviewBundle,
        hard_review_passed: bool,
        critic_result: LLMSQLCriticResult | None,
    ) -> dict[str, object]:
        return {
            "repair_attempt": repair_attempt,
            "hard_review_passed": hard_review_passed,
            "hard_checks": [check.model_dump() for check in review_bundle.hard_checks],
            "llm_decision": critic_result.decision.model_dump()
            if critic_result and critic_result.decision is not None
            else None,
            "llm_error": critic_result.llm_error if critic_result else None,
        }

    def _build_sql_critic_step(self, result: LLMSQLCriticResult) -> AgentStep:
        if result.decision is None:
            return AgentStep(
                name="sql_llm_review",
                status="failed",
                summary="SQL semantic critic did not approve the SQL.",
                details={
                    "status": result.status,
                    "llm_error": result.llm_error,
                    "llm_model": result.llm_model,
                    "llm_provider": result.llm_provider,
                },
            )

        return AgentStep(
            name="sql_llm_review",
            status="passed" if result.decision.passed else "failed",
            summary="Ran LLM semantic SQL critic.",
            details={
                "status": result.status,
                "decision": result.decision.model_dump(),
                "llm_error": result.llm_error,
                "llm_model": result.llm_model,
                "llm_provider": result.llm_provider,
            },
        )

    def _build_sql_execution_step(self, result: SQLLoopResult) -> AgentStep:
        if result.execution_result is None:
            return AgentStep(
                name="execute_sql",
                status="skipped",
                summary="SQL execution was skipped because SQL review did not pass.",
                details={"execution_history": result.execution_history or []},
            )

        return AgentStep(
            name="execute_sql",
            status="passed" if result.execution_result.status == "success" else "failed",
            summary="Executed SQL against PostgreSQL in a read-only transaction.",
            details={
                "status": result.execution_result.status,
                "row_count": result.execution_result.row_count,
                "response_preview_rows": min(
                    result.execution_result.row_count, self.result_preview_rows
                ),
                "columns": result.execution_result.columns,
                "truncated": result.execution_result.truncated,
                "elapsed_ms": result.execution_result.elapsed_ms,
                "error_type": result.execution_result.error_type,
                "error_message": result.execution_result.error_message,
                "execution_history": result.execution_history or [],
            },
        )

    def _build_result_validation_step(self, result: SQLLoopResult) -> AgentStep:
        if result.result_hard_validation is None:
            return AgentStep(
                name="result_hard_review",
                status="skipped",
                summary="Result hard validation was skipped because SQL did not execute.",
                details={},
            )

        return AgentStep(
            name="result_hard_review",
            status="passed" if result.result_hard_validation.passed else "failed",
            summary="Ran deterministic result hard validation.",
            details={
                "score": result.result_hard_validation.score,
                "error_type": result.result_hard_validation.error_type,
                "repair_hint": result.result_hard_validation.repair_hint,
                "checks": [check.model_dump() for check in result.result_hard_validation.checks],
            },
        )

    def _build_result_critic_step(self, result: SQLLoopResult) -> AgentStep:
        critic_result = result.result_critic_result
        if critic_result is None:
            return AgentStep(
                name="result_llm_review",
                status="skipped",
                summary="Result semantic critic was skipped.",
                details={},
            )
        if critic_result.decision is None:
            status = (
                "failed"
                if result.result_hard_validation is not None
                and result.result_hard_validation.passed
                else "skipped"
            )
            return AgentStep(
                name="result_llm_review",
                status=status,
                summary="Result semantic critic did not approve the result.",
                details={
                    "status": critic_result.status,
                    "llm_error": critic_result.llm_error,
                    "llm_model": critic_result.llm_model,
                    "llm_provider": critic_result.llm_provider,
                    "final_result_review_passed": result.result_validation.passed
                    if result.result_validation is not None
                    else None,
                },
            )

        return AgentStep(
            name="result_llm_review",
            status="passed" if critic_result.decision.passed else "failed",
            summary="Ran LLM semantic result critic.",
            details={
                "status": critic_result.status,
                "decision": critic_result.decision.model_dump(),
                "llm_error": critic_result.llm_error,
                "llm_model": critic_result.llm_model,
                "llm_provider": critic_result.llm_provider,
                "final_result_review_passed": result.result_validation.passed
                if result.result_validation is not None
                else None,
            },
        )

    def _build_execution_details(
        self,
        repair_attempt: int,
        execution_result: SQLExecutionResult,
        result_hard_validation: ResultValidationResult,
        result_validation: ResultValidationResult,
        result_critic_result: LLMResultCriticResult | None,
        execution_id: str | None,
    ) -> dict[str, object]:
        return {
            "repair_attempt": repair_attempt,
            "execution_id": execution_id,
            "execution_status": execution_result.status,
            "row_count": execution_result.row_count,
            "columns": execution_result.columns,
            "truncated": execution_result.truncated,
            "elapsed_ms": execution_result.elapsed_ms,
            "error_type": execution_result.error_type,
            "error_message": execution_result.error_message,
            "result_hard_validation_passed": result_hard_validation.passed,
            "result_critic_status": result_critic_result.status
            if result_critic_result is not None
            else None,
            "result_critic_passed": result_critic_result.decision.passed
            if result_critic_result is not None and result_critic_result.decision is not None
            else None,
            "result_validation_passed": result_validation.passed,
            "result_validation_error_type": result_validation.error_type,
            "result_validation_repair_hint": result_validation.repair_hint,
        }

    def _build_actor_details(
        self, result: QueryPlanBuildResult, build_results: list[QueryPlanBuildResult]
    ) -> dict[str, object]:
        return {
            "intent": result.plan.intent,
            "plan_status": result.plan.plan_status,
            "actor_source": result.source,
            "attempt_count": len(build_results),
            "repair_attempts": max(0, len(build_results) - 1),
            "llm_error": result.llm_error,
            "llm_model": result.llm_model,
            "llm_provider": result.llm_provider,
            "llm_unavailable_reason": self.llm_unavailable_reason,
            "attempts": [
                {
                    "repair_attempt": item.repair_attempt,
                    "actor_source": item.source,
                    "plan_status": item.plan.plan_status,
                    "intent": item.plan.intent,
                    "llm_error": item.llm_error,
                    "llm_model": item.llm_model,
                    "llm_provider": item.llm_provider,
                }
                for item in build_results
            ],
        }

    def _build_repair_step(
        self,
        repair_count: int,
        build_results: list[QueryPlanBuildResult],
        review_passed: bool,
    ) -> AgentStep:
        if repair_count == 0:
            return AgentStep(
                name="repair_query_plan",
                status="skipped",
                summary="No QueryPlan repair was required.",
                details={"max_repair_attempts": self.max_repair_attempts},
            )

        return AgentStep(
            name="repair_query_plan",
            status="passed" if review_passed else "failed",
            summary="Repaired QueryPlan with critic feedback.",
            details={
                "repair_count": repair_count,
                "max_repair_attempts": self.max_repair_attempts,
                "attempt_sources": [item.source for item in build_results],
            },
        )

    def _build_review_details(
        self,
        repair_attempt: int,
        review_bundle: ReviewBundle,
        hard_review_passed: bool,
        critic_result: LLMPlanCriticResult,
    ) -> dict[str, object]:
        return {
            "repair_attempt": repair_attempt,
            "hard_review_passed": hard_review_passed,
            "hard_checks": [check.model_dump() for check in review_bundle.hard_checks],
            "llm_decision": critic_result.decision.model_dump()
            if critic_result.decision is not None
            else None,
            "llm_error": critic_result.llm_error,
        }

    def _build_critic_step(self, result: LLMPlanCriticResult) -> AgentStep:
        if result.decision is None:
            return AgentStep(
                name="query_plan_llm_review",
                status="skipped",
                summary="Skipped semantic QueryPlan critic.",
                details={
                    "status": result.status,
                    "llm_error": result.llm_error,
                    "llm_model": result.llm_model,
                    "llm_provider": result.llm_provider,
                },
            )

        return AgentStep(
            name="query_plan_llm_review",
            status="passed" if result.decision.passed else "failed",
            summary="Ran LLM semantic QueryPlan critic.",
            details={
                "status": result.status,
                "decision": result.decision.model_dump(),
                "llm_error": result.llm_error,
                "llm_model": result.llm_model,
                "llm_provider": result.llm_provider,
            },
        )

    def _to_guardrail_checks(self, checks: list[ReviewDecision]) -> list[GuardrailCheck]:
        guardrail_checks: list[GuardrailCheck] = []
        for check in checks:
            name = check.error_type or (check.evidence[0] if check.evidence else check.stage)
            guardrail_checks.append(
                GuardrailCheck(
                    name=name,
                    passed=check.passed,
                    message=check.reason,
                    severity="info" if check.passed else "error",
                )
            )
        return guardrail_checks
