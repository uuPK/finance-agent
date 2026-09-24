from typing import Any

from app.guardrails.plan_grounding import ground_query_plan
from app.schemas.query_plan import QueryPlan
from app.schemas.review import ReviewBundle, ReviewDecision


class QueryPlanHardValidator:
    def review(
        self,
        plan: QueryPlan,
        *,
        original_question: str | None = None,
        metadata_context: dict[str, Any] | None = None,
    ) -> ReviewBundle:
        checks = [
            self._check_status_consistency(plan),
            self._check_subject(plan),
            self._check_metrics(plan),
            self._check_filters(plan),
            self._check_output(plan),
            self._check_confidence(plan),
        ]
        if original_question is not None and metadata_context is not None:
            checks.extend(self._check_grounding(plan, original_question, metadata_context))
        return ReviewBundle(hard_checks=checks)

    def _check_grounding(
        self, plan: QueryPlan, question: str, context: dict[str, Any]
    ) -> list[ReviewDecision]:
        if plan.plan_status != "ready":
            return [self._pass("grounding_deferred", "Grounding is deferred until clarification.")]

        checks: list[ReviewDecision] = []
        verified = ground_query_plan(plan, question, context)
        if verified.plan_status == "needs_clarification":
            checks.append(
                self._fail(
                    "ungrounded_business_definition",
                    "Ready plan depends on a business or time definition without evidence.",
                    [item.field for item in verified.clarifications],
                    "Ask clarification or apply a retrieved metadata definition.",
                )
            )
        else:
            checks.append(self._pass("business_definition_grounding", "Definitions are grounded."))
        missing_metric_sources = [
            metric.name
            for metric, grounded in zip(plan.metrics, verified.metrics, strict=True)
            if not any(
                ref.source_type == expected.source_type and ref.source_id == expected.source_id
                for ref in metric.provenance or []
                for expected in grounded.provenance or []
                if expected.source_type
                in {"user_explicit", "metadata_definition", "system_default"}
            )
        ]
        checks.append(
            self._fail(
                "ungrounded_metric",
                "Ready plan metric lacks verified provenance.",
                missing_metric_sources,
                "Attach the original-question or retrieved-metadata source.",
            )
            if missing_metric_sources
            else self._pass("metric_provenance", "Metrics have verified provenance.")
        )
        if plan.time_range is not None:
            time_grounded = any(
                ref.source_type == expected.source_type and ref.source_id == expected.source_id
                for ref in plan.time_range.provenance or []
                for expected in verified.time_range.provenance or []
                if expected.source_type
                in {"user_explicit", "metadata_definition", "system_default"}
            )
            checks.append(
                self._pass("time_provenance", "Time definition has verified provenance.")
                if time_grounded
                else self._fail(
                    "ungrounded_time",
                    "Ready plan time definition lacks evidence.",
                    [str(plan.time_range.label or plan.time_range.relative)],
                    "Use explicit user dates, a metadata default, or ask clarification.",
                )
            )
        original_filters = {
            (item.term, item.operator, str(item.value.normalized)) for item in plan.filters
        }
        unapplied = [
            item.term
            for item in verified.filters
            if (item.term, item.operator, str(item.value.normalized)) not in original_filters
            and item.provenance
            and item.provenance[0].source_type == "metadata_definition"
        ]
        checks.append(
            self._fail(
                "missing_metadata_definition_filter",
                "Ready plan omitted a retrieved business-term definition.",
                unapplied,
                "Apply the structured metadata definition before SQL generation.",
            )
            if unapplied
            else self._pass("metadata_default_applied", "Metadata defaults are applied.")
        )
        unsupported = [
            item.term
            for item in plan.filters
            if item.operator in {">", ">=", "<", "<=", "between"}
            and not any(
                ref.source_type == expected.source_type and ref.source_id == expected.source_id
                for matching in verified.filters
                if matching.term == item.term
                and matching.operator == item.operator
                and matching.value.normalized == item.value.normalized
                for ref in item.provenance or []
                for expected in matching.provenance or []
                if expected.source_type
                in {"user_explicit", "metadata_definition", "system_default"}
            )
        ]
        checks.append(
            self._fail(
                "ungrounded_threshold",
                "Ready plan contains a threshold without evidence.",
                unsupported,
                "Ask the user for the threshold or use a retrieved business definition.",
            )
            if unsupported
            else self._pass("threshold_provenance", "Thresholds have evidence.")
        )

        if context.get("source") == "database":
            metrics = {
                str(row.get("metric_code"))
                for row in context.get("metrics", [])
                if isinstance(row, dict) and row.get("metric_code")
            }
            unknown_metrics = sorted(
                {
                    code
                    for code in [
                        *(item.metric_code for item in plan.metrics),
                        *(item.metric_code for item in plan.filters),
                    ]
                    if code and code not in metrics
                }
            )
            checks.append(
                self._fail(
                    "fabricated_metric",
                    "Metric code is absent from retrieved metadata.",
                    unknown_metrics,
                    "Use a retrieved metric or request missing metadata.",
                )
                if unknown_metrics
                else self._pass("metric_grounding", "Metric codes are retrieved.")
            )

            columns = {
                str(column.get("name"))
                for table in context.get("tables", [])
                if isinstance(table, dict)
                for column in table.get("columns", [])
                if isinstance(column, dict) and column.get("name")
            }
            unknown_fields = sorted(
                {
                    code
                    for code in [
                        *(item.field_code for item in plan.filters),
                        *(item.dimension_code for item in plan.dimensions),
                    ]
                    if code and code not in columns and code not in metrics
                }
            )
            checks.append(
                self._fail(
                    "fabricated_field",
                    "Field code is absent from retrieved schema.",
                    unknown_fields,
                    "Use a retrieved column or request its metadata.",
                )
                if unknown_fields
                else self._pass("field_grounding", "Field codes are retrieved.")
            )

            tables = set(context.get("table_allowlist") or [])
            unknown_tables = sorted(
                table
                for table in set(plan.data_requirements.candidate_tables)
                if table.removeprefix("mart.") not in tables
            )
            checks.append(
                self._fail(
                    "fabricated_table",
                    "Candidate table is absent from retrieved schema.",
                    unknown_tables,
                    "Remove the table or request its metadata.",
                )
                if unknown_tables
                else self._pass("table_grounding", "Candidate tables are retrieved.")
            )

            join_rows = [
                row for row in context.get("join_relationships", []) if isinstance(row, dict)
            ]
            valid_joins = {str(row.get("id")) for row in join_rows if row.get("id") is not None}
            valid_joins.update(f"join:{join_id}" for join_id in tuple(valid_joins))
            valid_joins.update(
                f"{row.get('left_table')}.{row.get('left_column')}="
                f"{row.get('right_table')}.{row.get('right_column')}"
                for row in join_rows
            )
            unknown_joins = sorted(set(plan.data_requirements.required_join_paths) - valid_joins)
            checks.append(
                self._fail(
                    "fabricated_join",
                    "Join path is absent from retrieved metadata.",
                    unknown_joins,
                    "Use a retrieved join path or request join metadata.",
                )
                if unknown_joins
                else self._pass("join_grounding", "Join paths are retrieved.")
            )

            terms = {
                str(row.get("term"))
                for row in context.get("business_terms", [])
                if isinstance(row, dict) and row.get("term")
            }
            references = [
                *plan.data_requirements.required_metadata_refs,
                *(item.metadata_ref for item in plan.metrics if item.metadata_ref),
                *(item.metadata_ref for item in plan.filters if item.metadata_ref),
                *(item.metadata_ref for item in plan.dimensions if item.metadata_ref),
            ]
            unknown_refs = []
            for ref in references:
                key = ref.code or ref.ref_id or ref.name
                code = key.split(":", 1)[-1]
                known = {
                    "metric": code in metrics,
                    "business_term": code in terms,
                    "table": code.removeprefix("mart.") in tables,
                    "column": code.rsplit(".", 1)[-1] in columns,
                    "join_path": code in valid_joins,
                    "example": True,
                }.get(ref.ref_type, False)
                if not known:
                    unknown_refs.append(f"{ref.ref_type}:{key}")
            checks.append(
                self._fail(
                    "fabricated_metadata_ref",
                    "Metadata reference is not retrievable.",
                    sorted(set(unknown_refs)),
                    "Use a retrieved metadata reference.",
                )
                if unknown_refs
                else self._pass("metadata_ref_grounding", "Metadata references exist.")
            )
        return checks

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
        # Confidence is produced by a probabilistic actor.  It is useful audit
        # evidence, but it is not a safety or structural invariant: the SQL
        # guardrail and result validation below still make the execution
        # decision.  Treating it as a hard stop made otherwise explicit,
        # metadata-backed multi-table questions fail before SQL was attempted.
        if plan.plan_status == "ready" and plan.confidence < 0.7:
            return self._pass(
                "confidence_advisory",
                "Ready plan confidence is advisory; downstream guardrails remain required.",
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
