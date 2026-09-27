"""Structural safeguards no longer depend on an official-question phrase list."""

from app.agents.llm_query_plan_actor import QueryPlanBuildResult
from app.schemas.query_plan import QueryMetric, QueryOutput, QueryPlan
from app.services.query_service import QueryService


def _plans() -> tuple[QueryPlan, QueryPlan]:
    metric = QueryMetric(
        name="量子风险评分", metric_code="quantum_risk_score", alias="量子风险评分"
    )
    deterministic = QueryPlan(
        plan_status="ready", question="统计量子风险评分",
        metrics=[metric], output=QueryOutput(columns=["量子风险评分"]),
    )
    incomplete = deterministic.model_copy(update={"metrics": []})
    return deterministic, incomplete


def test_new_catalog_metric_can_complete_output_without_python_phrase_map() -> None:
    deterministic, incomplete = _plans()
    result = QueryService._apply_rule_plan_safeguards(
        QueryPlanBuildResult(plan=incomplete, source="llm"), deterministic,
        {"source": "database", "metrics": [{"metric_code": "quantum_risk_score"}]},
    )
    assert result.source == "rule_fallback"
    assert [metric.metric_code for metric in result.plan.metrics] == ["quantum_risk_score"]


def test_missing_catalog_definition_does_not_force_unverified_rule_metric() -> None:
    deterministic, incomplete = _plans()
    result = QueryService._apply_rule_plan_safeguards(
        QueryPlanBuildResult(plan=incomplete, source="llm"), deterministic,
        {"source": "database", "metrics": []},
    )
    assert result.source == "llm"
    assert result.plan.metrics == []


def test_filter_only_metric_is_not_forced_into_output() -> None:
    deterministic, incomplete = _plans()
    metric = deterministic.metrics[0]
    deterministic.output.columns = ["客户数量"]
    incomplete.metrics = [metric]
    assert QueryService._output_metrics_from_metadata(
        deterministic, {"metrics": [{"metric_code": "quantum_risk_score"}]}
    ) == []
