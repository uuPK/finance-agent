from dataclasses import dataclass

import sqlglot
from sqlglot import exp


@dataclass(frozen=True)
class GuardrailFinding:
    name: str
    passed: bool
    message: str
    severity: str = "info"


class SQLGuardrail:
    def __init__(
        self,
        allowed_tables: set[str] | None = None,
        sensitive_columns: set[str] | None = None,
        require_limit: bool = True,
    ) -> None:
        self.allowed_tables = allowed_tables or set()
        self.sensitive_columns = sensitive_columns or set()
        self.require_limit = require_limit

    def validate(self, sql: str) -> list[GuardrailFinding]:
        findings: list[GuardrailFinding] = []

        try:
            expression = sqlglot.parse_one(sql, read="postgres")
        except sqlglot.errors.ParseError as exc:
            return [
                GuardrailFinding(
                    name="sql_parse",
                    passed=False,
                    message=f"SQL parse failed: {exc}",
                    severity="error",
                )
            ]

        findings.append(self._check_select_only(expression))
        findings.append(self._check_forbidden_expressions(expression))
        findings.extend(self._check_allowed_tables(expression))
        findings.extend(self._check_sensitive_columns(expression))

        if self.require_limit:
            findings.append(self._check_limit(expression))

        return findings

    def _check_select_only(self, expression: exp.Expression) -> GuardrailFinding:
        passed = isinstance(expression, exp.Select)
        return GuardrailFinding(
            name="select_only",
            passed=passed,
            message="Only SELECT statements are allowed." if not passed else "SQL is read-only.",
            severity="error" if not passed else "info",
        )

    def _check_forbidden_expressions(self, expression: exp.Expression) -> GuardrailFinding:
        forbidden_type_names = ("Delete", "Drop", "Insert", "Update", "Create", "Alter", "TruncateTable")
        forbidden_types = tuple(
            expression_type
            for type_name in forbidden_type_names
            if (expression_type := getattr(exp, type_name, None)) is not None
        )
        found = [node.key for node in expression.walk() if isinstance(node, forbidden_types)]
        passed = not found
        return GuardrailFinding(
            name="forbidden_operations",
            passed=passed,
            message=(
                "No forbidden write or DDL operations found."
                if passed
                else f"Forbidden SQL operations found: {', '.join(found)}"
            ),
            severity="error" if not passed else "info",
        )

    def _check_allowed_tables(self, expression: exp.Expression) -> list[GuardrailFinding]:
        if not self.allowed_tables:
            return [
                GuardrailFinding(
                    name="table_whitelist",
                    passed=True,
                    message="Table whitelist is not configured yet.",
                    severity="warning",
                )
            ]

        findings: list[GuardrailFinding] = []
        table_names = {table.name for table in expression.find_all(exp.Table)}
        for table_name in sorted(table_names):
            passed = table_name in self.allowed_tables
            findings.append(
                GuardrailFinding(
                    name="table_whitelist",
                    passed=passed,
                    message=(
                        f"Table `{table_name}` is allowed."
                        if passed
                        else f"Table `{table_name}` is not in metadata whitelist."
                    ),
                    severity="error" if not passed else "info",
                )
            )
        return findings

    def _check_sensitive_columns(self, expression: exp.Expression) -> list[GuardrailFinding]:
        if not self.sensitive_columns:
            return [
                GuardrailFinding(
                    name="sensitive_columns",
                    passed=True,
                    message="Sensitive column list is not configured yet.",
                    severity="warning",
                )
            ]

        findings: list[GuardrailFinding] = []
        selected_columns = {column.name for column in expression.find_all(exp.Column)}
        for column_name in sorted(selected_columns & self.sensitive_columns):
            findings.append(
                GuardrailFinding(
                    name="sensitive_columns",
                    passed=False,
                    message=f"Column `{column_name}` is sensitive and cannot be returned.",
                    severity="error",
                )
            )

        if not findings:
            findings.append(
                GuardrailFinding(
                    name="sensitive_columns",
                    passed=True,
                    message="No sensitive columns are selected.",
                )
            )
        return findings

    def _check_limit(self, expression: exp.Expression) -> GuardrailFinding:
        passed = expression.args.get("limit") is not None
        return GuardrailFinding(
            name="limit_required",
            passed=passed,
            message="SQL has LIMIT." if passed else "SQL must include LIMIT for preview queries.",
            severity="error" if not passed else "info",
        )
