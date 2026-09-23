import pytest
from pydantic import BaseModel, ValidationError

from app.schemas.query_plan import (
    MetadataReference,
    PlanAssumption,
    QueryDimension,
    QueryFilter,
    QueryMetric,
    QueryPlan,
    QueryValue,
    TimeRange,
)
from app.schemas.v2_protocol import (
    EvidenceRef,
    FailureEvent,
    HarnessAction,
    MissingContextRequest,
)


def test_legacy_query_plan_payload_remains_valid_without_provenance() -> None:
    metadata_ref = MetadataReference(
        ref_type="metric", ref_id="metric:total_asset", code="total_asset", name="总资产"
    )
    plan = QueryPlan(
        question="统计总资产",
        metrics=[
            QueryMetric(
                name="总资产",
                metric_code="total_asset",
                metadata_ref=metadata_ref,
                is_resolved=True,
            )
        ],
        filters=[
            QueryFilter(
                term="地区",
                operator="=",
                value=QueryValue(raw="上海"),
                source="user",
            )
        ],
        dimensions=[QueryDimension(name="客户类型", dimension_code="cust_type")],
        time_range=TimeRange(label="2026年第一季度", start="20260101", end="20260331"),
        assumptions=[PlanAssumption(field="币种", value="人民币", reason="系统默认口径")],
    )

    assert plan.metrics[0].metadata_ref == metadata_ref
    assert plan.filters[0].source == "user"
    assert plan.metrics[0].provenance is None
    assert plan.filters[0].provenance is None
    assert plan.dimensions[0].provenance is None
    assert plan.time_range is not None and plan.time_range.provenance is None
    assert plan.assumptions[0].provenance is None


def test_evidence_ref_supports_all_protocol_sources_and_validates_confidence() -> None:
    sources = (
        "user_explicit",
        "metadata_definition",
        "system_default",
        "llm_inferred",
    )
    evidence = [
        EvidenceRef(source_type=source, source_text="证据文本", confidence=0.8)
        for source in sources
    ]

    metric = QueryMetric(name="总资产", provenance=evidence)

    assert [item.source_type for item in metric.provenance or []] == list(sources)
    with pytest.raises(ValidationError):
        EvidenceRef(source_type="user_explicit", source_text="文本", confidence=1.1)


def test_missing_context_request_carries_targeted_retrieval_details() -> None:
    request = MissingContextRequest(
        type="join_path",
        concept="客户到基金交易",
        from_table="customer",
        to_table="fund_transaction",
        reason="当前上下文中没有关联路径",
        priority="high",
    )

    assert request.type == "join_path"
    assert request.from_table == "customer"
    assert request.to_table == "fund_transaction"
    assert request.priority == "high"
    with pytest.raises(ValidationError):
        MissingContextRequest(
            type="unsupported", concept="x", reason="reason", priority="urgent"
        )


def test_failure_event_captures_stage_evidence_and_retryability() -> None:
    event = FailureEvent(
        stage="execution",
        error_type="query_timeout",
        evidence=["statement timeout", "elapsed_ms=30000"],
        repair_hint="检查查询复杂度",
        retryable=False,
    )

    assert event.stage == "execution"
    assert event.evidence == ["statement timeout", "elapsed_ms=30000"]
    assert event.retryable is False
    with pytest.raises(ValidationError):
        FailureEvent(stage="answer", error_type="unknown")


def test_harness_action_is_restricted_to_the_v2_action_set() -> None:
    class ActionEnvelope(BaseModel):
        action: HarnessAction

    expected = {
        "CONTINUE",
        "PLAN_REPAIR",
        "SQL_REPAIR",
        "CONTEXT_REFRESH",
        "RETRY_EXECUTION",
        "CLARIFY",
        "TERMINATE",
    }

    assert {action.value for action in HarnessAction} == expected
    assert ActionEnvelope(action="SQL_REPAIR").action is HarnessAction.SQL_REPAIR
    with pytest.raises(ValidationError):
        ActionEnvelope(action="RESTART_EVERYTHING")
