"""Run-scoped orchestration; QueryService remains the public API facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from app.agents.llm_plan_critic import LLMPlanCriticResult
from app.agents.llm_query_plan_actor import QueryPlanBuildResult
from app.guardrails.result_validator import ResultValidationResult
from app.schemas.query_plan import QueryPlan
from app.schemas.review import ReviewBundle
from app.services.harness_state import HarnessState
from app.services.trace_facts import context_facts, plan_facts

if TYPE_CHECKING:
    from app.services.query_service import QueryService, SQLLoopResult


@dataclass(slots=True)
class PlanPhaseResult:
    query_plan: QueryPlan
    metadata_context: dict[str, object]
    build_result: QueryPlanBuildResult
    build_results: list[QueryPlanBuildResult]
    review_bundle: ReviewBundle
    hard_review_passed: bool
    critic_result: LLMPlanCriticResult
    review_history: list[dict[str, object]]


class QueryHarness:
    """Owns phase transitions and repair reservations, not model or SQL tools."""

    def __init__(self, service: QueryService, state: HarnessState) -> None:
        self.service = service
        self.state = state

    async def prepare_plan(
        self, question: str, previous_plan: QueryPlan | None = None
    ) -> PlanPhaseResult:
        service = self.service
        await service._emit("receive_question", "running", "正在接收业务问题")
        await service._emit("receive_question", "passed", "已接收业务问题", {"question": question})

        await service._emit("retrieve_metadata", "running", "正在检索相关元数据")
        metadata_context = service._load_metadata_context(question)
        await service._record_trace("context_selection", lambda: context_facts(metadata_context))
        await service._emit(
            "retrieve_metadata",
            "passed" if metadata_context.get("source") == "database" else "failed",
            "已完成元数据检索",
            service._metadata_context_summary(metadata_context),
        )
        await service._emit("build_query_plan", "running", "正在生成结构化查询计划")
        build_result = await service.query_plan_actor.build(
            question,
            fallback_plan=previous_plan,
            previous_plan=previous_plan,
            metadata_context=metadata_context,
        )
        deterministic_plan = service.rule_based_actor.build(question)
        build_result = service._apply_rule_plan_safeguards(build_result, deterministic_plan)
        query_plan = build_result.plan
        build_results = [build_result]
        metadata_context = service._load_metadata_context(
            question, query_plan, previous_context=metadata_context
        )
        query_plan, metadata_context = service._ground_plan_with_context(
            question, query_plan, metadata_context
        )
        build_result.plan = query_plan
        await service._record_trace("context_selection", lambda: context_facts(metadata_context))
        await service._record_trace("plan_evidence", lambda: plan_facts(query_plan))
        await service._emit(
            "build_query_plan",
            "passed",
            "查询计划已生成并核对证据来源",
            {
                "query_plan": query_plan.model_dump(mode="json", exclude_none=True),
                **service._build_actor_details(build_result, build_results),
            },
        )
        review_bundle, hard_review_passed, critic_result = await service._review_query_plan(
            query_plan, metadata_context, attempt=0, original_question=question
        )
        review_history = [
            service._build_review_details(
                build_result.repair_attempt,
                review_bundle,
                hard_review_passed,
                critic_result,
            )
        ]

        while self.should_repair_plan(query_plan, review_bundle):
            repair_feedback = service._failed_review_feedback(review_bundle)
            repair_count = self.state.reserve_repair("plan")
            await service._emit(
                "repair_query_plan",
                "running",
                f"正在进行第 {repair_count} 次查询计划修复",
                {"feedback": [item.model_dump(mode="json") for item in repair_feedback]},
                attempt=repair_count,
            )
            build_result = await service.query_plan_actor.build(
                question,
                fallback_plan=query_plan,
                previous_plan=query_plan,
                critic_feedback=repair_feedback,
                metadata_context=metadata_context,
                repair_attempt=repair_count,
            )
            build_result = service._apply_rule_plan_safeguards(build_result, deterministic_plan)
            build_results.append(build_result)
            query_plan = build_result.plan
            metadata_context = service._load_metadata_context(
                question, query_plan, previous_context=metadata_context
            )
            query_plan, metadata_context = service._ground_plan_with_context(
                question, query_plan, metadata_context
            )
            build_result.plan = query_plan
            await service._record_trace(
                "context_selection", lambda context=metadata_context: context_facts(context)
            )
            await service._record_trace("plan_evidence", lambda plan=query_plan: plan_facts(plan))
            await service._emit(
                "repair_query_plan",
                "passed" if build_result.source == "llm" else "failed",
                f"第 {repair_count} 次查询计划修复已完成",
                {
                    "query_plan": query_plan.model_dump(mode="json", exclude_none=True),
                    "actor_source": build_result.source,
                    "llm_error": build_result.llm_error,
                },
                attempt=repair_count,
            )
            review_bundle, hard_review_passed, critic_result = await service._review_query_plan(
                query_plan,
                metadata_context,
                attempt=repair_count,
                original_question=question,
            )
            review_history.append(
                service._build_review_details(
                    build_result.repair_attempt,
                    review_bundle,
                    hard_review_passed,
                    critic_result,
                )
            )
            if build_result.source != "llm":
                break

        if not review_bundle.passed and not self.state.can_repair("plan"):
            await service._emit(
                "plan_repair_budget",
                "failed",
                "查询计划修复预算已耗尽",
                self.state.budget_facts("plan"),
                event_type="budget.exhausted",
            )

        return PlanPhaseResult(
            query_plan=query_plan,
            metadata_context=metadata_context,
            build_result=build_result,
            build_results=build_results,
            review_bundle=review_bundle,
            hard_review_passed=hard_review_passed,
            critic_result=critic_result,
            review_history=review_history,
        )

    def should_repair_plan(self, query_plan: QueryPlan, review_bundle: ReviewBundle) -> bool:
        if review_bundle.passed or not self.state.can_repair("plan"):
            return False
        if not self.service.llm_enabled or query_plan.plan_status == "invalid":
            return False
        if query_plan.plan_status == "needs_clarification":
            return bool(self.service._failed_review_feedback(review_bundle))
        return True

    def should_repair_sql(
        self, review_bundle: ReviewBundle, result_validation: ResultValidationResult | None
    ) -> bool:
        if review_bundle.passed and result_validation is not None and result_validation.passed:
            return False
        if not self.state.can_repair("sql") or not self.service.llm_enabled:
            return False
        if not review_bundle.passed:
            return bool(self.service._failed_review_feedback(review_bundle))
        if result_validation is not None:
            return bool(self.service._failed_result_feedback(result_validation))
        return False

    async def run_sql(
        self,
        query_id: UUID,
        question: str,
        query_plan: QueryPlan,
        metadata_context: dict[str, object],
    ) -> SQLLoopResult:
        return await self.service._run_sql_loop(
            query_id, question, query_plan, metadata_context, harness=self
        )
