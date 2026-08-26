from uuid import uuid4

import pytest

from app.guardrails.sql_guardrail import SQLGuardrail
from app.schemas.evaluation import ReviewDecisionInput
from app.services.evaluation_service import EvaluationRepository


@pytest.fixture
def guardrail() -> SQLGuardrail:
    return SQLGuardrail(
        allowed_tables={"customer_profile"},
        allowed_columns_by_table={"customer_profile": {"customer_id", "customer_name"}},
        sensitive_columns={"customer_name"},
    )


@pytest.mark.parametrize(
    ("sql", "finding_name"),
    [
        (
            "select customer_id into mart.customer_profile "
            "from mart.customer_profile limit 1",
            "forbidden_operations",
        ),
        (
            "select customer_id from mart.customer_profile limit 1 for update",
            "forbidden_operations",
        ),
        (
            "with recursive nums(n) as (select 1 union all select n + 1 from nums where n < 3) "
            "select customer_id from mart.customer_profile limit 1",
            "recursive_cte",
        ),
        (
            "select customer_id from mart.customer_profile limit 1 offset 10001",
            "offset_max_rows",
        ),
    ],
)
def test_rejects_resource_or_stateful_select_variants(
    guardrail: SQLGuardrail, sql: str, finding_name: str
) -> None:
    findings = {finding.name: finding for finding in guardrail.validate(sql)}

    assert findings[finding_name].passed is False


def test_metadata_context_guardrail_applies_table_column_and_sensitive_policy() -> None:
    guardrail = SQLGuardrail.from_metadata_context(
        {
            "table_allowlist": ["customer_profile"],
            "allowed_columns_by_table": {
                "customer_profile": ["customer_id", "customer_name"],
            },
            "sensitive_columns": ["customer_name"],
        }
    )

    findings = {finding.name: finding for finding in guardrail.validate(
        "select customer_name from mart.customer_profile limit 1"
    )}

    assert findings["table_whitelist"].passed is True
    assert findings["column_whitelist"].passed is True
    assert findings["sensitive_columns"].passed is False


class _SchemaContext:
    def __init__(self, context: dict[str, object]) -> None:
        self.context = context

    def load(self) -> dict[str, object]:
        return self.context


def test_review_promotion_requires_live_physical_metadata() -> None:
    repository = EvaluationRepository()
    repository.schema_context_provider = _SchemaContext({"source": "unavailable"})  # type: ignore[assignment]

    assert repository._review_sql_guardrail() is None

    repository.schema_context_provider = _SchemaContext(  # type: ignore[assignment]
        {
            "source": "database",
            "table_allowlist": ["customer_profile"],
            "allowed_columns_by_table": {
                "customer_profile": ["customer_id", "customer_name"],
            },
            "sensitive_columns": ["customer_name"],
        }
    )
    review_guardrail = repository._review_sql_guardrail()

    assert review_guardrail is not None
    findings = {
        finding.name: finding
        for finding in review_guardrail.validate(
            "select customer_name from mart.customer_profile"
        )
    }
    assert findings["sensitive_columns"].passed is False


class _RecordingConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def execute(self, statement: object, params: dict[str, object]) -> None:
        self.calls.append((str(statement), params))


def test_clarification_review_never_wipes_expected_result_without_a_complete_plan() -> None:
    repository = EvaluationRepository()
    connection = _RecordingConnection()
    item = {"case_id": uuid4()}
    incomplete_decision = ReviewDecisionInput(
        review_item_id=uuid4(),
        reviewer_id="reviewer",
        verdict="needs_clarification",
    )

    repository._promote_review_feedback(connection, item, incomplete_decision)

    assert connection.calls == []

    complete_decision = incomplete_decision.model_copy(
        update={"corrected_query_plan": {"clarifications": [{"field": "date"}]}}
    )
    repository._promote_review_feedback(connection, item, complete_decision)

    statement, params = connection.calls[0]
    assert "expected_result" not in statement
    assert "result" not in params
