import pytest
from pydantic import ValidationError

from app.schemas.evaluation import ReviewDecisionInput
from app.schemas.metadata import MetadataMetricInput


def test_manual_metric_requires_a_stable_safe_code() -> None:
    metric = MetadataMetricInput(
        metric_code="customer_value_score",
        metric_name="客户价值评分",
        formula="sum(score)",
        source_tables=["ads_cust_info_d"],
    )
    assert metric.metric_code == "customer_value_score"
    with pytest.raises(ValidationError):
        MetadataMetricInput(metric_code="客户价值", metric_name="客户价值", formula="sum(score)")


def test_review_decision_can_carry_an_optional_metadata_change() -> None:
    decision = ReviewDecisionInput(
        review_item_id="4d0c36ce-bb85-4ddb-8c4c-dc736e008d3f",
        reviewer_id="reviewer-01",
        verdict="incorrect",
        error_class="insufficient_metadata",
        metadata_changes=[
            {
                "action": "create",
                "kind": "term",
                "payload": {
                    "term": "客户价值评分",
                    "definition": "由业务人员确认后维护的客户评分口径。",
                },
            }
        ],
    )
    assert decision.metadata_changes[0].kind == "term"
