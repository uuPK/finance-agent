from time import perf_counter

from app.agents.plan_reviewer import QueryPlanHardValidator
from app.agents.query_plan_actor import RuleBasedQueryPlanActor
from app.schemas.query import AgentStep, GuardrailCheck, QueryRequest, QueryResponse
from app.schemas.review import ReviewDecision


class QueryService:
    def __init__(self) -> None:
        self.query_plan_actor = RuleBasedQueryPlanActor()
        self.plan_validator = QueryPlanHardValidator()

    async def run(self, request: QueryRequest) -> QueryResponse:
        started_at = perf_counter()

        query_plan = self.query_plan_actor.build(request.question)
        review_bundle = self.plan_validator.review(query_plan)
        hard_checks = review_bundle.hard_checks
        review_passed = review_bundle.passed

        if query_plan.plan_status == "needs_clarification":
            status = "needs_clarification"
            answer = "The request needs clarification before SQL generation."
        elif review_passed:
            status = "planned"
            answer = (
                "QueryPlan is ready. SQL generation is paused until metadata and database "
                "integration are enabled."
            )
        else:
            status = "failed"
            answer = "QueryPlan failed hard validation and needs repair before SQL generation."

        elapsed_ms = int((perf_counter() - started_at) * 1000)

        return QueryResponse(
            status=status,
            answer=answer,
            query_plan=query_plan,
            sql=None,
            result_preview=[],
            guardrail_checks=self._to_guardrail_checks(hard_checks),
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
                    summary="Built QueryPlan with offline rule-based actor.",
                    details={"intent": query_plan.intent, "plan_status": query_plan.plan_status},
                ),
                AgentStep(
                    name="query_plan_hard_review",
                    status="passed" if review_passed else "failed",
                    summary="Ran deterministic QueryPlan hard checks.",
                    details={"checks": [check.model_dump() for check in hard_checks]},
                ),
            ],
            elapsed_ms=elapsed_ms,
        )

    def _to_guardrail_checks(self, checks: list[ReviewDecision]) -> list[GuardrailCheck]:
        guardrail_checks: list[GuardrailCheck] = []
        for check in checks:
            guardrail_checks.append(
                GuardrailCheck(
                    name=check.error_type or check.evidence[0],
                    passed=check.passed,
                    message=check.reason,
                    severity="info" if check.passed else "error",
                )
            )
        return guardrail_checks
