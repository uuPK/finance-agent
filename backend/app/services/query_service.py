from dataclasses import dataclass
from time import perf_counter

from app.agents.llm_plan_critic import LLMPlanCritic, LLMPlanCriticResult
from app.agents.llm_query_plan_actor import LLMQueryPlanActor, QueryPlanBuildResult
from app.agents.llm_sql_actor import LLMSQLActor, SQLBuildResult
from app.agents.llm_sql_critic import LLMSQLCritic, LLMSQLCriticResult
from app.agents.plan_reviewer import QueryPlanHardValidator
from app.agents.query_plan_actor import RuleBasedQueryPlanActor
from app.guardrails.sql_guardrail import GuardrailFinding, SQLGuardrail
from app.llm.protocols import SupportsLLMComplete
from app.metadata.schema_context import SchemaContextProvider
from app.schemas.query import AgentStep, GuardrailCheck, QueryRequest, QueryResponse
from app.schemas.query_plan import QueryPlan
from app.schemas.review import ReviewBundle, ReviewDecision
from app.schemas.sql import SQLDraft


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
    failure_reason: str | None = None


class QueryService:
    def __init__(
        self,
        llm_service: SupportsLLMComplete | None = None,
        enable_llm: bool = True,
        max_repair_attempts: int = 2,
        schema_context_provider: SchemaContextProvider | None = None,
    ) -> None:
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
        self.schema_context_provider = schema_context_provider or SchemaContextProvider()
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

    async def run(self, request: QueryRequest) -> QueryResponse:
        started_at = perf_counter()

        build_result = await self.query_plan_actor.build(request.question)
        query_plan = build_result.plan
        build_results = [build_result]
        review_bundle, hard_review_passed, critic_result = await self._review_query_plan(
            query_plan
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
            build_result = await self.query_plan_actor.build(
                request.question,
                fallback_plan=query_plan,
                previous_plan=query_plan,
                critic_feedback=repair_feedback,
                repair_attempt=repair_count,
            )
            build_results.append(build_result)

            if build_result.source != "llm":
                break

            query_plan = build_result.plan
            review_bundle, hard_review_passed, critic_result = await self._review_query_plan(
                query_plan
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

        if query_plan.plan_status == "invalid":
            status = "failed"
            answer = "The request is invalid for the current QueryPlan safety policy."
        elif not review_passed:
            status = "failed"
            answer = "QueryPlan failed review and needs repair before SQL generation."
        elif query_plan.plan_status == "needs_clarification":
            status = "needs_clarification"
            answer = "The request needs clarification before SQL generation."
        else:
            sql_loop_result = await self._run_sql_loop(request.question, query_plan)
            if sql_loop_result.passed:
                status = "planned"
                answer = (
                    "QueryPlan and SQL are ready against the current database schema context. "
                    "SQL execution is not enabled in the main query loop yet."
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
        sql_steps = (
            self._build_sql_steps(sql_loop_result) if sql_loop_result is not None else []
        )
        sql = sql_loop_result.sql if sql_loop_result and sql_loop_result.passed else None
        total_retry_count = repair_count + (
            sql_loop_result.repair_count if sql_loop_result is not None else 0
        )

        elapsed_ms = int((perf_counter() - started_at) * 1000)
        all_checks = [
            *review_bundle.hard_checks,
            *review_bundle.llm_checks,
            *sql_checks,
        ]

        return QueryResponse(
            status=status,
            answer=answer,
            query_plan=query_plan,
            sql=sql,
            result_preview=[],
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
                        "checks": [
                            check.model_dump() for check in review_bundle.hard_checks
                        ],
                        "review_history": review_history,
                    },
                ),
                self._build_critic_step(critic_result),
                *sql_steps,
            ],
            retry_count=total_retry_count,
            elapsed_ms=elapsed_ms,
        )

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
        self, query_plan: QueryPlan
    ) -> tuple[ReviewBundle, bool, LLMPlanCriticResult]:
        review_bundle = self.plan_validator.review(query_plan)
        hard_review_passed = all(check.passed for check in review_bundle.hard_checks)

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
            critic_result = await self.plan_critic.review(
                query_plan, review_bundle.hard_checks
            )
            if critic_result.decision is not None:
                review_bundle.llm_checks.append(critic_result.decision)

        return review_bundle, hard_review_passed, critic_result

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

    async def _run_sql_loop(self, question: str, query_plan: QueryPlan) -> SQLLoopResult:
        metadata_context = self.schema_context_provider.load(query_plan)
        build_result = await self.sql_actor.build(
            question=question,
            query_plan=query_plan,
            metadata_context=metadata_context,
        )
        build_results = [build_result]

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
                failure_reason=build_result.llm_error or "SQL generation failed.",
            )

        review_bundle, hard_review_passed, critic_result = await self._review_sql_draft(
            query_plan, build_result.draft, metadata_context
        )
        review_history = [
            self._build_sql_review_details(
                build_result.repair_attempt,
                review_bundle,
                hard_review_passed,
                critic_result,
            )
        ]

        repair_count = 0
        while self._should_repair_sql(review_bundle, repair_count):
            repair_feedback = self._failed_review_feedback(review_bundle)
            previous_sql = build_result.draft.sql
            repair_count += 1
            build_result = await self.sql_actor.build(
                question=question,
                query_plan=query_plan,
                metadata_context=metadata_context,
                previous_sql=previous_sql,
                critic_feedback=repair_feedback,
                repair_attempt=repair_count,
            )
            build_results.append(build_result)

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

            review_bundle, hard_review_passed, critic_result = await self._review_sql_draft(
                query_plan, build_result.draft, metadata_context
            )
            review_history.append(
                self._build_sql_review_details(
                    build_result.repair_attempt,
                    review_bundle,
                    hard_review_passed,
                    critic_result,
                )
            )

        passed = review_bundle.passed
        sql = build_result.draft.sql if passed and build_result.draft is not None else None
        failure_reason = None if passed else "SQL generation failed review before execution."

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
            failure_reason=failure_reason,
        )

    async def _review_sql_draft(
        self,
        query_plan: QueryPlan,
        sql_draft: SQLDraft,
        metadata_context: dict[str, object],
    ) -> tuple[ReviewBundle, bool, LLMSQLCriticResult]:
        guardrail_findings = self._build_sql_guardrail(metadata_context).validate(
            sql_draft.sql
        )
        hard_checks = [
            self._guardrail_finding_to_review_decision(finding)
            for finding in guardrail_findings
        ]
        review_bundle = ReviewBundle(hard_checks=hard_checks)
        hard_review_passed = all(check.passed for check in hard_checks)

        critic_result = LLMSQLCriticResult(
            status="failed",
            llm_error="Hard SQL review failed; SQLCritic skipped.",
        )
        if hard_review_passed:
            critic_result = await self.sql_critic.review(
                query_plan=query_plan,
                sql_draft=sql_draft,
                hard_checks=hard_checks,
            )
            if critic_result.decision is not None:
                decision = self._enforce_sql_critic_confidence(critic_result.decision)
                review_bundle.llm_checks.append(decision)
            else:
                review_bundle.llm_checks.append(
                    self._sql_critic_failure_decision(critic_result)
                )

        return review_bundle, hard_review_passed, critic_result

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

    def _should_repair_sql(self, review_bundle: ReviewBundle, repair_count: int) -> bool:
        if review_bundle.passed:
            return False
        if repair_count >= self.max_repair_attempts:
            return False
        if not self.llm_enabled:
            return False
        return bool(self._failed_review_feedback(review_bundle))

    def _guardrail_finding_to_review_decision(
        self, finding: GuardrailFinding
    ) -> ReviewDecision:
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
                    "checks": [
                        check.model_dump() for check in result.review_bundle.hard_checks
                    ],
                    "review_history": result.review_history,
                },
            ),
            self._build_sql_critic_step(result.critic_result),
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

    def _metadata_context_summary(
        self, metadata_context: dict[str, object]
    ) -> dict[str, object]:
        table_allowlist = self._string_list(metadata_context.get("table_allowlist"))
        metrics = metadata_context.get("metrics")
        metric_codes = []
        if isinstance(metrics, list):
            metric_codes = [
                metric["metric_code"]
                for metric in metrics
                if isinstance(metric, dict) and isinstance(metric.get("metric_code"), str)
            ]
        return {
            "source": metadata_context.get("source"),
            "error": metadata_context.get("error"),
            "table_count": metadata_context.get("table_count", 0),
            "metric_count": metadata_context.get("metric_count", 0),
            "tables": table_allowlist,
            "metrics": metric_codes,
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
            "hard_checks": [
                check.model_dump() for check in review_bundle.hard_checks
            ],
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
            "hard_checks": [
                check.model_dump() for check in review_bundle.hard_checks
            ],
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
