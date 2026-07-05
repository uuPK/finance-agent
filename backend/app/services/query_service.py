from time import perf_counter

from app.agents.llm_plan_critic import LLMPlanCritic, LLMPlanCriticResult
from app.agents.llm_query_plan_actor import LLMQueryPlanActor, QueryPlanBuildResult
from app.agents.plan_reviewer import QueryPlanHardValidator
from app.agents.query_plan_actor import RuleBasedQueryPlanActor
from app.llm.protocols import SupportsLLMComplete
from app.schemas.query import AgentStep, GuardrailCheck, QueryRequest, QueryResponse
from app.schemas.review import ReviewDecision


class QueryService:
    def __init__(
        self,
        llm_service: SupportsLLMComplete | None = None,
        enable_llm: bool = True,
    ) -> None:
        self.rule_based_actor = RuleBasedQueryPlanActor()
        self.plan_validator = QueryPlanHardValidator()
        self.llm_unavailable_reason: str | None = None

        resolved_llm_service = llm_service
        if resolved_llm_service is None and enable_llm:
            resolved_llm_service, self.llm_unavailable_reason = self._build_default_llm_service()
        elif not enable_llm:
            self.llm_unavailable_reason = "LLM is disabled for this QueryService instance."

        self.query_plan_actor = LLMQueryPlanActor(
            llm_service=resolved_llm_service,
            fallback_actor=self.rule_based_actor,
        )
        self.plan_critic = LLMPlanCritic(llm_service=resolved_llm_service)

    async def run(self, request: QueryRequest) -> QueryResponse:
        started_at = perf_counter()

        build_result = await self.query_plan_actor.build(request.question)
        query_plan = build_result.plan
        review_bundle = self.plan_validator.review(query_plan)
        hard_checks = review_bundle.hard_checks
        hard_review_passed = all(check.passed for check in hard_checks)

        critic_result = LLMPlanCriticResult(
            status="skipped",
            llm_error="Hard review failed; semantic critic skipped.",
        )
        if hard_review_passed:
            critic_result = await self.plan_critic.review(query_plan, hard_checks)
            if critic_result.decision is not None:
                review_bundle.llm_checks.append(critic_result.decision)

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
                    details=self._build_actor_details(build_result),
                ),
                AgentStep(
                    name="query_plan_hard_review",
                    status="passed" if hard_review_passed else "failed",
                    summary="Ran deterministic QueryPlan hard checks.",
                    details={"checks": [check.model_dump() for check in hard_checks]},
                ),
                self._build_critic_step(critic_result),
            ],
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

    def _build_actor_details(self, result: QueryPlanBuildResult) -> dict[str, object]:
        return {
            "intent": result.plan.intent,
            "plan_status": result.plan.plan_status,
            "actor_source": result.source,
            "llm_error": result.llm_error,
            "llm_model": result.llm_model,
            "llm_provider": result.llm_provider,
            "llm_unavailable_reason": self.llm_unavailable_reason,
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
