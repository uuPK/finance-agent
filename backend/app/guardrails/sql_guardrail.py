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
        max_limit: int = 1000,
    ) -> None:
        self.allowed_tables = allowed_tables or set()
        self.sensitive_columns = sensitive_columns or set()
        self.require_limit = require_limit
        self.max_limit = max_limit

    def validate(self, sql: str) -> list[GuardrailFinding]:
        findings: list[GuardrailFinding] = []

        try:
            statements = [
                statement
                for statement in sqlglot.parse(sql, read="postgres")
                if statement
            ]
        except sqlglot.errors.ParseError as exc:
            return [
                GuardrailFinding(
                    name="sql_parse",
                    passed=False,
                    message=f"SQL parse failed: {exc}",
                    severity="error",
                )
            ]

        if len(statements) != 1:
            return [
                GuardrailFinding(
                    name="single_statement",
                    passed=False,
                    message="SQL must contain exactly one statement.",
                    severity="error",
                )
            ]

        expression = statements[0]
        findings.append(
            GuardrailFinding(
                name="single_statement",
                passed=True,
                message="SQL contains exactly one statement.",
            )
        )
        findings.append(self._check_select_only(expression))
        findings.append(self._check_forbidden_expressions(expression))
        findings.append(self._check_no_select_star(expression))
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
        forbidden_type_names = (
            "Delete",
            "Drop",
            "Insert",
            "Update",
            "Create",
            "Alter",
            "TruncateTable",
        )
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

    def _check_no_select_star(self, expression: exp.Expression) -> GuardrailFinding:
        found_star = any(
            isinstance(projection, exp.Star)
            or (
                isinstance(projection, exp.Column)
                and isinstance(projection.this, exp.Star)
            )
            for projection in expression.expressions
        )
        return GuardrailFinding(
            name="select_star",
            passed=not found_star,
            message=(
                "SQL does not use SELECT *."
                if not found_star
                else "SQL must not use SELECT *; select explicit columns or expressions."
            ),
            severity="error" if found_star else "info",
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
        limit = expression.args.get("limit")
        if limit is None:
            return GuardrailFinding(
                name="limit_required",
                passed=False,
                message="SQL must include LIMIT for preview queries.",
                severity="error",
            )

        limit_value = self._extract_limit_value(limit)
        if limit_value is None:
            return GuardrailFinding(
                name="limit_value",
                passed=False,
                message="SQL LIMIT must be a positive integer literal.",
                severity="error",
            )

        if limit_value <= 0:
            return GuardrailFinding(
                name="limit_value",
                passed=False,
                message="SQL LIMIT must be positive.",
                severity="error",
            )

        if limit_value > self.max_limit:
            return GuardrailFinding(
                name="limit_max_rows",
                passed=False,
                message=f"SQL LIMIT {limit_value} exceeds max rows {self.max_limit}.",
                severity="error",
            )

        return GuardrailFinding(
            name="limit_required",
            passed=True,
            message=f"SQL has LIMIT {limit_value}.",
        )

    def _extract_limit_value(self, limit: exp.Expression) -> int | None:
        expression = limit.args.get("expression")
        if isinstance(expression, exp.Literal) and expression.is_int:
            return int(expression.this)
        return None
