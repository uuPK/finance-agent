from app.guardrails.sql_guardrail import SQLGuardrail


def test_sql_guardrail_rejects_multi_statement_sql() -> None:
    findings = SQLGuardrail().validate(
        "SELECT customer_id FROM customer_info LIMIT 10; DROP TABLE x"
    )

    assert any(not finding.passed and finding.name == "single_statement" for finding in findings)


def test_sql_guardrail_rejects_select_star() -> None:
    findings = SQLGuardrail().validate("SELECT * FROM customer_info LIMIT 10")

    assert any(not finding.passed and finding.name == "select_star" for finding in findings)


def test_sql_guardrail_rejects_limit_above_max_rows() -> None:
    findings = SQLGuardrail(max_limit=100).validate(
        "SELECT customer_id FROM customer_info LIMIT 1000"
    )

    assert any(not finding.passed and finding.name == "limit_max_rows" for finding in findings)
