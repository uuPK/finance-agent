from app.schemas.query_plan import QueryPlan
from app.schemas.review import ReviewBundle, ReviewDecision


class QueryPlanHardValidator:
    def review(self, plan: QueryPlan) -> ReviewBundle:
        checks = [
            self._check_status_consistency(plan),
            self._check_subject(plan),
            self._check_metrics(plan),
            self._check_filters(plan),
            self._check_output(plan),
            self._check_confidence(plan),
        ]
        return ReviewBundle(hard_checks=checks)

    def _check_status_consistency(self, plan: QueryPlan) -> ReviewDecision:
        if plan.clarifications and plan.plan_status != "needs_clarification":
            return self._fail(
                "status_clarification_mismatch",
                "Plan has clarification questions but status is not needs_clarification.",
                ["clarifications is not empty"],
                "Set plan_status=needs_clarification and skip SQL generation.",
            )
        if not plan.clarifications and plan.plan_status == "needs_clarification":
            return self._fail(
                "unnecessary_clarification_status",
                "Plan status asks for clarification but no clarification question exists.",
                ["plan_status=needs_clarification", "clarifications is empty"],
                "Add clarification questions or change plan_status.",
            )
        return self._pass("status_consistency", "Plan status is consistent with clarifications.")

    def _check_subject(self, plan: QueryPlan) -> ReviewDecision:
        if plan.intent != "metadata_question" and plan.subject is None:
            return self._fail(
                "missing_subject",
                "QueryPlan has no subject for a concrete data query.",
                ["subject is null"],
                "Identify whether the query is about customers, products, managers, or campaigns.",
            )
        return self._pass("subject", "Query subject is present.")

    def _check_metrics(self, plan: QueryPlan) -> ReviewDecision:
        if plan.plan_status == "needs_clarification" and plan.clarifications:
            return self._pass(
                "metrics_deferred",
                "Metric checks are deferred because the plan requires clarification.",
            )
        metric_required = plan.intent in {
            "metric_query",
            "customer_segmentation",
            "ranking_query",
        }
        if metric_required and not plan.metrics:
            return self._fail(
                "missing_metric",
                "QueryPlan has no metric for a metric-bearing query.",
                [f"intent={plan.intent}", "metrics is empty"],
                "Add metrics requested by the user, or ask clarification if no metric can be "
                "inferred.",
            )
        unresolved = [metric.name for metric in plan.metrics if metric.requires_clarification]
        if unresolved and plan.plan_status != "needs_clarification":
            return self._fail(
                "unresolved_metric",
                "Some metrics require clarification but plan is not marked needs_clarification.",
                unresolved,
                "Add clarification questions or resolve the metric definitions.",
            )
        return self._pass("metrics", "Metric requirements are structurally acceptable.")

    def _check_filters(self, plan: QueryPlan) -> ReviewDecision:
        unresolved = [
            query_filter.term
            for query_filter in plan.filters
            if query_filter.requires_clarification
        ]
        if unresolved and plan.plan_status != "needs_clarification":
            return self._fail(
                "unresolved_filter",
                "Some filters require clarification but plan is not marked needs_clarification.",
                unresolved,
                "Add clarification questions or resolve filter definitions.",
            )
        return self._pass("filters", "Filter requirements are structurally acceptable.")

    def _check_output(self, plan: QueryPlan) -> ReviewDecision:
        if plan.output.limit <= 0:
            return self._fail(
                "invalid_limit",
                "Output limit must be positive.",
                [f"limit={plan.output.limit}"],
                "Set output.limit to a positive value.",
            )
        if plan.output.limit > plan.safety.max_rows:
            return self._fail(
                "limit_exceeds_safety",
                "Output limit exceeds safety max_rows.",
                [f"limit={plan.output.limit}", f"max_rows={plan.safety.max_rows}"],
                "Lower output.limit or raise safety.max_rows through policy.",
            )
        return self._pass("output", "Output settings satisfy hard constraints.")

    def _check_confidence(self, plan: QueryPlan) -> ReviewDecision:
        if plan.plan_status == "ready" and plan.confidence < 0.7:
            return self._fail(
                "low_confidence",
                "Ready plan confidence is below the auto-pass threshold.",
                [f"confidence={plan.confidence}"],
                "Ask clarification or improve metadata retrieval before SQL generation.",
            )
        return self._pass("confidence", "Plan confidence satisfies hard policy.")

    def _pass(self, name: str, reason: str) -> ReviewDecision:
        return ReviewDecision(
            passed=True,
            score=100,
            stage="query_plan_review",
            reason=reason,
            evidence=[name],
            confidence=1.0,
        )

    def _fail(
        self, error_type: str, reason: str, evidence: list[str], repair_hint: str
    ) -> ReviewDecision:
        return ReviewDecision(
            passed=False,
            score=0,
            stage="query_plan_review",
            error_type=error_type,
            reason=reason,
            evidence=evidence,
            repair_hint=repair_hint,
            confidence=1.0,
        )
