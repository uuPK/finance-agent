import os
from uuid import uuid4

import pytest

from app.core.config import get_settings
from app.guardrails.sql_guardrail import SQLGuardrail
from app.metadata.schema_context import SchemaContextProvider
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
            "select customer_id into mart.customer_profile from mart.customer_profile limit 1",
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

    findings = {
        finding.name: finding
        for finding in guardrail.validate("select customer_name from mart.customer_profile limit 1")
    }

    assert findings["table_whitelist"].passed is True
    assert findings["column_whitelist"].passed is True
    assert findings["sensitive_columns"].passed is False


def _join_context() -> dict[str, object]:
    return {
        "source": "database",
        "table_allowlist": ["ads_cust_info_d", "dwd_cust_hold_d", "dim_product"],
        "allowed_columns_by_table": {
            "ads_cust_info_d": ["pty_id", "org_id"],
            "dwd_cust_hold_d": ["pty_id", "prdt_id"],
            "dim_product": ["prdt_id", "prdt_name"],
        },
        "join_relationship_allowlist": [
            {
                "left_table": "ads_cust_info_d",
                "left_column": "pty_id",
                "right_table": "dwd_cust_hold_d",
                "right_column": "pty_id",
            },
            {
                "left_table": "dwd_cust_hold_d",
                "left_column": "prdt_id",
                "right_table": "dim_product",
                "right_column": "prdt_id",
            },
        ],
    }


def test_direct_multihop_joins_match_authoritative_metadata_keys() -> None:
    guardrail = SQLGuardrail.from_metadata_context(_join_context())
    findings = guardrail.validate(
        "select c.pty_id, p.prdt_name from mart.ads_cust_info_d c "
        "join mart.dwd_cust_hold_d h on h.pty_id = c.pty_id "
        "join mart.dim_product p on p.prdt_id = h.prdt_id limit 10"
    )

    paths = [item for item in findings if item.name == "join_path_consistency"]
    assert len(paths) == 2
    assert all(item.passed for item in paths)
    assert not any(not item.passed and item.severity == "error" for item in findings)


def test_reverse_join_aliases_match_approved_key_in_either_direction() -> None:
    findings = SQLGuardrail.from_metadata_context(_join_context()).validate(
        "select h.pty_id from mart.dwd_cust_hold_d h "
        "join mart.ads_cust_info_d c on c.pty_id = h.pty_id limit 10"
    )
    assert any(item.name == "join_path_consistency" and item.passed for item in findings)


def test_using_join_requires_same_column_approved_path() -> None:
    guardrail = SQLGuardrail.from_metadata_context(_join_context())
    approved = guardrail.validate(
        "select c.pty_id from mart.ads_cust_info_d c "
        "join mart.dwd_cust_hold_d h using (pty_id) limit 10"
    )
    rejected = guardrail.validate(
        "select c.pty_id from mart.ads_cust_info_d c "
        "join mart.dwd_cust_hold_d h using (org_id) limit 10"
    )
    assert any(item.name == "join_path_consistency" and item.passed for item in approved)
    assert any(item.name == "join_path_consistency" and not item.passed for item in rejected)


@pytest.mark.parametrize(
    "join_clause",
    [
        "join mart.dwd_cust_hold_d h on h.prdt_id = c.pty_id",
        "join mart.dim_product h on h.prdt_id = c.org_id",
        "join mart.dwd_cust_hold_d h on h.pty_id = c.pty_id or h.prdt_id = c.org_id",
    ],
)
def test_wrong_or_unregistered_direct_join_is_blocked(join_clause: str) -> None:
    findings = SQLGuardrail.from_metadata_context(_join_context()).validate(
        "select c.pty_id from mart.ads_cust_info_d c " + join_clause + " limit 10"
    )
    assert any(item.name == "join_path_consistency" and not item.passed for item in findings)


@pytest.mark.parametrize(
    "join_clause",
    ["cross join mart.dwd_cust_hold_d h", "join mart.dwd_cust_hold_d h on true"],
)
def test_cartesian_join_is_blocked_without_explain(join_clause: str) -> None:
    findings = SQLGuardrail.from_metadata_context(_join_context()).validate(
        "select c.pty_id from mart.ads_cust_info_d c " + join_clause + " limit 10"
    )
    assert any(item.name == "cartesian_join" and not item.passed for item in findings)


def test_join_on_derived_cte_is_advisory_not_guessed_as_physical_path() -> None:
    findings = SQLGuardrail.from_metadata_context(_join_context()).validate(
        "with customer_snapshot as (select pty_id from mart.ads_cust_info_d limit 10) "
        "select c.pty_id from customer_snapshot c "
        "join mart.dwd_cust_hold_d h on h.pty_id = c.pty_id limit 10"
    )
    paths = [item for item in findings if item.name == "join_path_consistency"]
    assert len(paths) == 1
    assert paths[0].passed and paths[0].severity == "warning"


def test_missing_authoritative_join_catalog_remains_advisory_for_legacy_context() -> None:
    context = _join_context()
    context.pop("join_relationship_allowlist")
    findings = SQLGuardrail.from_metadata_context(context).validate(
        "select c.pty_id from mart.ads_cust_info_d c "
        "join mart.dwd_cust_hold_d h on h.pty_id = c.pty_id limit 10"
    )
    paths = [item for item in findings if item.name == "join_path_consistency"]
    assert len(paths) == 1
    assert paths[0].passed and paths[0].severity == "warning"


@pytest.mark.skipif(
    os.getenv("RUN_TRACE_DB_TESTS") != "1", reason="requires local PostgreSQL metadata catalog"
)
def test_live_context_join_policy_is_complete_not_retrieval_limited() -> None:
    settings = get_settings().model_copy(update={"retriever_mode": "legacy"})
    context = SchemaContextProvider(settings=settings).load(question="客户持仓产品")

    assert context["source"] == "database"
    assert len(context["join_relationship_allowlist"]) >= len(context["join_relationships"])
    keys = {
        (row["left_table"], row["left_column"], row["right_table"], row["right_column"])
        for row in context["join_relationship_allowlist"]
    }
    assert ("dwd_cust_hold_d", "prdt_id", "dim_product", "prdt_id") in keys


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
        for finding in review_guardrail.validate("select customer_name from mart.customer_profile")
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
