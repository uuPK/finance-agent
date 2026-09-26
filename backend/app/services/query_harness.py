"""Run-scoped orchestration; QueryService remains the public API facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlglot import exp, parse_one

from app.agents.llm_plan_critic import LLMPlanCriticResult
from app.agents.llm_query_plan_actor import QueryPlanBuildResult
from app.guardrails.result_validator import ResultValidationResult
from app.schemas.query_plan import QueryPlan
from app.schemas.review import ReviewBundle, ReviewDecision
from app.schemas.sql import SQLDraft
from app.schemas.v2_protocol import FailureEvent, HarnessAction, MissingContextRequest
from app.services.failure_router import (
    FailureRouter,
    RouteDecision,
    classify_unknown_column,
    safe_error_type,
)
from app.services.harness_state import HarnessState
from app.services.sql_executor import SQLExecutionResult
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
        self.router = FailureRouter()

    async def route_failure(
        self,
        failure: FailureEvent,
        *,
        source_stage: str,
        source_attempt: int,
        allow_retry: bool = True,
        allow_context_refresh: bool = False,
    ) -> RouteDecision:
        """Apply model availability and budget after the pure router proposes an action."""
        candidate = self.router.propose(failure)
        final = candidate
        reason = "routed"
        domain = (
            "plan"
            if candidate == HarnessAction.PLAN_REPAIR
            else "sql"
            if candidate == HarnessAction.SQL_REPAIR
            else None
        )
        if candidate == HarnessAction.TERMINATE:
            reason = (
                "non_retryable_failure"
                if not failure.retryable
                else {
                    "column_not_found": "schema_context_evidence_missing",
                    "stale_metadata_schema": "metadata_refresh_required",
                    "timeout": "timeout_classification_required",
                }.get(failure.error_type, "conservative_terminate")
            )
        elif candidate == HarnessAction.CONTEXT_REFRESH:
            if not allow_context_refresh:
                final = HarnessAction.TERMINATE
                reason = "context_refresh_evidence_missing"
            elif not self.state.can_refresh_context():
                final = HarnessAction.TERMINATE
                reason = "budget_exhausted"
        elif domain is None:
            final = HarnessAction.TERMINATE
            reason = "action_not_implemented"
        elif not allow_retry:
            final = HarnessAction.TERMINATE
            reason = "actor_fallback"
        elif not self.service.llm_enabled:
            final = HarnessAction.TERMINATE
            reason = "model_unavailable"
        elif not self.state.can_repair(domain):
            final = HarnessAction.TERMINATE
            reason = "budget_exhausted"

        route = RouteDecision(
            route_id=uuid4(),
            route_attempt=self.state.next_route_attempt(),
            failure_stage=failure.stage,
            error_type=safe_error_type(failure.error_type, "unclassified_failure"),
            source_stage=source_stage,
            source_attempt=source_attempt,
            candidate_action=candidate,
            final_action=final,
            reason_code=reason,
        )
        source = self.state.stages.get((source_stage, source_attempt))
        budget = None
        if domain is not None:
            will_reserve = final == candidate
            used = self.state.repair_used(domain) + int(will_reserve)
            limit = self.state.repair_limit(domain)
            budget = {
                "domain": domain,
                "used": used,
                "limit": limit,
                "exhausted": used >= limit,
                "reserved": will_reserve,
            }
        elif candidate == HarnessAction.CONTEXT_REFRESH and allow_context_refresh:
            used = self.state.context_refreshes_used + int(final == candidate)
            limit = self.state.max_context_refreshes
            budget = {
                "domain": "context",
                "used": used,
                "limit": limit,
                "exhausted": used >= limit,
                "reserved": final == candidate,
            }
        await self.service._emit(
            "failure_router",
            "passed",
            "失败路由决策已确定",
            {
                "route_id": str(route.route_id),
                "failure_stage": failure.stage,
                "error_type": route.error_type,
                "retryable": failure.retryable,
                "evidence_count": len(failure.evidence),
                "source_stage": source_stage,
                "source_attempt": source_attempt,
                "source_span_id": str(source.span_id) if source and source.span_id else None,
                "candidate_action": candidate.value,
                "final_action": final.value,
                "reason_code": reason,
                "budget": budget,
            },
            attempt=route.route_attempt,
            event_type="route.decided",
        )
        if reason == "budget_exhausted" and domain is not None:
            await self.service._emit(
                f"{domain}_repair_budget",
                "failed",
                "修复预算已耗尽",
                {"route_id": str(route.route_id), **self.state.budget_facts(domain)},
                event_type="budget.exhausted",
            )
        elif reason == "budget_exhausted" and candidate == HarnessAction.CONTEXT_REFRESH:
            await self.service._emit(
                "context_refresh_budget",
                "failed",
                "Context 刷新预算已耗尽",
                {
                    "route_id": str(route.route_id),
                    "domain": "context",
                    "used": self.state.context_refreshes_used,
                    "limit": self.state.max_context_refreshes,
                    "exhausted": True,
                },
                event_type="budget.exhausted",
            )
        if domain is not None and final == candidate:
            self.state.reserve_repair(domain)
        elif final == HarnessAction.CONTEXT_REFRESH:
            self.state.reserve_context_refresh()
        else:
            await self.record_route_execution(route, "terminated")
        return route

    async def record_route_execution(self, route: RouteDecision, outcome: str) -> None:
        await self.service._emit(
            "harness_action",
            "failed" if outcome in {"failed", "not_found"} else "passed",
            "路由动作已处理",
            {
                "route_id": str(route.route_id),
                "final_action": route.final_action.value,
                "outcome": outcome,
            },
            attempt=route.route_attempt,
            event_type="route.executed",
        )

    async def refresh_context(
        self,
        route: RouteDecision,
        *,
        question: str,
        query_plan: QueryPlan,
        current_context: dict[str, object],
        table_name: str,
        column_name: str,
    ) -> tuple[dict[str, object], bool]:
        allowlist = current_context.get("table_allowlist")
        if not isinstance(allowlist, list) or table_name not in allowlist:
            await self.record_route_execution(route, "not_found")
            return current_context, False
        request = MissingContextRequest(
            type="column",
            concept=column_name,
            from_table=table_name,
            reason="Live schema contains this column but the current SQL context does not.",
            priority="high",
        )
        await self.service._emit(
            "refresh_context",
            "running",
            "正在按实时数据库结构刷新 SQL 上下文",
            {"table": table_name, "column": column_name},
            attempt=route.route_attempt,
        )
        refreshed = self.service.schema_context_provider.expand(
            current_context,
            request,
            question=question,
            query_plan=query_plan,
        )
        columns = refreshed.get("allowed_columns_by_table")
        table_columns = columns.get(table_name) if isinstance(columns, dict) else None
        found = isinstance(table_columns, list) and column_name in table_columns
        await self.service._record_trace("context_selection", lambda: context_facts(refreshed))
        await self.service._emit(
            "refresh_context",
            "passed" if found else "failed",
            "已刷新 SQL 上下文" if found else "刷新后仍未找到该数据库字段",
            {
                "table": table_name,
                "column_present": found,
                "context_item_ids": (refreshed.get("context_bundle") or {}).get("item_ids", [])
                if isinstance(refreshed.get("context_bundle"), dict)
                else [],
            },
            attempt=route.route_attempt,
        )
        await self.record_route_execution(route, "applied" if found else "not_found")
        return refreshed, found

    @staticmethod
    def _first_failed(review_bundle: ReviewBundle) -> ReviewDecision | None:
        return next(
            (
                item
                for item in [*review_bundle.hard_checks, *review_bundle.llm_checks]
                if not item.passed
            ),
            None,
        )

    def plan_failure(self, plan: QueryPlan, review_bundle: ReviewBundle) -> FailureEvent:
        item = self._first_failed(review_bundle)
        return FailureEvent(
            stage="plan",
            error_type=safe_error_type(item.error_type if item else None, "plan_review_failed"),
            evidence=item.evidence if item else [],
            repair_hint=item.repair_hint if item else None,
            retryable=plan.plan_status != "invalid",
        )

    def sql_failure(
        self,
        review_bundle: ReviewBundle,
        result_validation: ResultValidationResult | None,
        execution_result: SQLExecutionResult | None,
        sql_draft: SQLDraft | None = None,
        metadata_context: dict[str, object] | None = None,
    ) -> FailureEvent:
        if not review_bundle.passed:
            item = self._first_failed(review_bundle)
            return FailureEvent(
                stage="sql",
                error_type=safe_error_type(item.error_type if item else None, "sql_review_failed"),
                evidence=item.evidence if item else [],
                repair_hint=item.repair_hint if item else None,
                retryable=True,
            )
        if execution_result is not None and execution_result.status != "success":
            error_type = safe_error_type(execution_result.error_type, "sql_execution_error")
            if error_type == "column_not_found":
                error_type = self._classify_unknown_column(
                    execution_result, sql_draft, metadata_context or {}
                )
            return FailureEvent(
                stage="execution",
                error_type=error_type,
                retryable=True,
            )
        item = (
            next((check for check in result_validation.checks if not check.passed), None)
            if result_validation is not None
            else None
        )
        return FailureEvent(
            stage="result",
            error_type=safe_error_type(item.error_type if item else None, "result_review_failed"),
            evidence=item.evidence if item else [],
            repair_hint=item.repair_hint if item else None,
            retryable=True,
        )

    def _classify_unknown_column(
        self,
        execution_result: SQLExecutionResult,
        sql_draft: SQLDraft | None,
        metadata_context: dict[str, object],
    ) -> str:
        column_name = execution_result.missing_column
        allowlist_value = metadata_context.get("table_allowlist")
        allowed_tables = (
            {item for item in allowlist_value if isinstance(item, str)}
            if isinstance(allowlist_value, list)
            else set()
        )
        if not column_name or sql_draft is None or not allowed_tables:
            return "column_not_found"
        try:
            parsed = parse_one(sql_draft.sql, read="postgres")
        except Exception:
            return "column_not_found"
        parsed_tables = list(parsed.find_all(exp.Table))
        if any(not table.db or table.db.lower() != "mart" for table in parsed_tables):
            return "column_not_found"
        sql_tables = {table.name for table in parsed_tables if table.name in allowed_tables}
        draft_tables = {
            name.rsplit(".", 1)[-1]
            for name in sql_draft.tables
            if name.rsplit(".", 1)[0] in {"", "mart"}
        }
        if len(sql_tables) != 1 or draft_tables != sql_tables:
            return "column_not_found"
        table_name = next(iter(sql_tables))
        raw_context_columns = metadata_context.get("allowed_columns_by_table")
        table_columns = (
            raw_context_columns.get(table_name) if isinstance(raw_context_columns, dict) else None
        )
        context_has_column = isinstance(table_columns, list) and any(
            isinstance(item, str) and item.casefold() == column_name.casefold()
            for item in table_columns
        )
        live_schema_has_column = self.service.schema_context_provider.physical_column_exists(
            table_name, column_name
        )
        return classify_unknown_column(
            live_schema_has_column=live_schema_has_column,
            context_has_column=context_has_column,
        )

    async def route_sql_generation_failure(self, source_stage: str, source_attempt: int) -> None:
        await self.route_failure(
            FailureEvent(stage="sql", error_type="sql_generation_failed", retryable=False),
            source_stage=source_stage,
            source_attempt=source_attempt,
        )

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

        actor_repairable = True
        while not review_bundle.passed:
            failure = self.plan_failure(query_plan, review_bundle)
            source_stage = (
                "query_plan_hard_review"
                if any(not item.passed for item in review_bundle.hard_checks)
                else "query_plan_llm_review"
            )
            route = await self.route_failure(
                failure,
                source_stage=source_stage,
                source_attempt=build_result.repair_attempt,
                allow_retry=actor_repairable,
            )
            if route.final_action != HarnessAction.PLAN_REPAIR:
                break
            repair_feedback = service._failed_review_feedback(review_bundle)
            repair_count = self.state.plan_repairs_used
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
            await self.record_route_execution(
                route, "applied" if build_result.source == "llm" else "failed"
            )
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
            actor_repairable = build_result.source == "llm"

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
