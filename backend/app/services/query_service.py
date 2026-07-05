from time import perf_counter

from app.agents.llm_plan_critic import LLMPlanCritic, LLMPlanCriticResult
from app.agents.llm_query_plan_actor import LLMQueryPlanActor, QueryPlanBuildResult
from app.agents.plan_reviewer import QueryPlanHardValidator
from app.agents.query_plan_actor import RuleBasedQueryPlanActor
from app.llm.protocols import SupportsLLMComplete
from app.schemas.query import AgentStep, GuardrailCheck, QueryRequest, QueryResponse
from app.schemas.query_plan import QueryPlan
from app.schemas.review import ReviewBundle, ReviewDecision


class QueryService:
    def __init__(
        self,
        llm_service: SupportsLLMComplete | None = None,
        enable_llm: bool = True,
        max_repair_attempts: int = 2,
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

        if not review_passed:
            status = "failed"
            answer = "QueryPlan failed review and needs repair before SQL generation."
        elif query_plan.plan_status == "needs_clarification":
            status = "needs_clarification"
            answer = "The request needs clarification before SQL generation."
        else:
            status = "planned"
            answer = (
                "QueryPlan is ready. SQL generation is paused until metadata and database "
                "integration are enabled."
            )

        elapsed_ms = int((perf_counter() - started_at) * 1000)
        all_checks = [*review_bundle.hard_checks, *review_bundle.llm_checks]

        return QueryResponse(
            status=status,
            answer=answer,
            query_plan=query_plan,
            sql=None,
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
            ],
            retry_count=repair_count,
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
        if hard_review_passed:
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
        if getattr(query_plan, "plan_status", None) == "needs_clarification":
            return bool(self._failed_review_feedback(review_bundle))
        return True

    def _failed_review_feedback(self, review_bundle: ReviewBundle) -> list[ReviewDecision]:
        return [
            check
            for check in [*review_bundle.hard_checks, *review_bundle.llm_checks]
            if not check.passed
        ]

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
