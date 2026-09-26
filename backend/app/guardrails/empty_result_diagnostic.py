"""Bounded, read-only diagnosis for a zero-row single-table AND query."""

from __future__ import annotations

from collections.abc import Mapping

import sqlglot
from sqlalchemy.engine import Engine
from sqlglot import exp

from app.guardrails.sql_guardrail import SQLGuardrail
from app.schemas.query import EmptyResultDiagnosis
from app.services.sql_executor import SQLExecutor

_COMPARISONS = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Like, exp.ILike)
_MAX_PREDICATES = 3


class EmptyResultDiagnosticValidator:
    """Inspect filter intersections without changing or rerunning the user query."""

    def __init__(
        self,
        *,
        engine: Engine | None = None,
        timeout_seconds: int = 3,
        executor: SQLExecutor | None = None,
    ) -> None:
        # A misconfigured diagnostic must not inherit the main query's long timeout.
        self.executor = executor or SQLExecutor(
            engine=engine, timeout_seconds=min(max(timeout_seconds, 1), 5), max_result_rows=1
        )

    def diagnose(self, sql: str, metadata_context: Mapping[str, object]) -> EmptyResultDiagnosis:
        try:
            statements = [
                statement for statement in sqlglot.parse(sql, read="postgres") if statement
            ]
        except sqlglot.errors.ParseError:
            return self._outcome("unsupported", "sql_parse_failed")
        if len(statements) != 1 or not isinstance(statements[0], exp.Select):
            return self._outcome("unsupported", "unsupported_sql_shape")
        query = statements[0]
        if (
            any(
                query.args.get(key)
                for key in (
                    "with_",
                    "joins",
                    "group",
                    "having",
                    "qualify",
                    "windows",
                    "offset",
                    "distinct",
                    "laterals",
                    "locks",
                    "sample",
                    "connect",
                )
            )
            or len(list(query.find_all(exp.Select))) != 1
        ):
            return self._outcome("unsupported", "unsupported_sql_shape")

        source = query.args.get("from_")
        table = source.this if isinstance(source, exp.From) else None
        if (
            not isinstance(table, exp.Table)
            or source.expressions
            or table.db != "mart"
            or table.catalog
            or table.args.get("sample")
        ):
            return self._outcome("unsupported", "unsupported_sql_shape")
        allowlist = metadata_context.get("table_allowlist")
        raw_columns = metadata_context.get("allowed_columns_by_table")
        allowed_columns = raw_columns.get(table.name) if isinstance(raw_columns, dict) else None
        if (
            metadata_context.get("source") != "database"
            or not isinstance(allowlist, list)
            or table.name not in allowlist
            or not isinstance(allowed_columns, list)
        ):
            return self._outcome("unsupported", "physical_schema_unavailable")
        original_guardrail = SQLGuardrail.from_metadata_context(metadata_context)
        if any(
            not finding.passed and finding.severity == "error"
            for finding in original_guardrail.validate(sql)
        ):
            return self._outcome("unsupported", "original_guardrail_rejected")

        where = query.args.get("where")
        if not isinstance(where, exp.Where):
            return self._outcome("unsupported", "and_filter_required")
        predicates = self._split_and(where.this)
        if not 2 <= len(predicates) <= _MAX_PREDICATES:
            return self._outcome("unsupported", "predicate_count_unsupported")
        if not all(
            self._safe_predicate(predicate, table.name, table.alias, set(allowed_columns))
            for predicate in predicates
        ):
            return self._outcome("unsupported", "predicate_shape_unsupported", len(predicates))

        conditions = [predicate.sql(dialect="postgres") for predicate in predicates]
        prefixes = [" AND ".join(conditions[:index]) for index in range(2, len(conditions) + 1)]
        names = [f"individual_{index}" for index in range(1, len(conditions) + 1)]
        names += [f"prefix_{index}" for index in range(2, len(conditions) + 1)]
        filters = [*conditions, *prefixes]
        projections = [
            f"COUNT(*) FILTER (WHERE {condition}) AS {name}"
            for name, condition in zip(names, filters, strict=True)
        ]
        probe_sql = f"SELECT {', '.join(projections)} FROM {table.sql(dialect='postgres')}"
        guardrail = SQLGuardrail.from_metadata_context(metadata_context, require_limit=False)
        if any(
            not finding.passed and finding.severity == "error"
            for finding in guardrail.validate(probe_sql)
        ):
            return self._outcome("unsupported", "probe_guardrail_rejected", len(predicates))

        try:
            result = self.executor.execute(probe_sql)
        except Exception:
            return self._outcome("probe_failed", "probe_execution_failed", len(predicates))
        if result.status != "success" or result.row_count != 1 or len(result.rows) != 1:
            return self._outcome("probe_failed", "probe_execution_failed", len(predicates))
        row = result.rows[0]
        counts = [row.get(name) for name in names]
        if any(type(count) is not int or count < 0 for count in counts):
            return self._outcome("probe_failed", "probe_payload_invalid", len(predicates))
        individual_nonempty = [count > 0 for count in counts[: len(predicates)]]
        prefix_nonempty = [count > 0 for count in counts[len(predicates) :]]
        if prefix_nonempty[-1]:
            status, reason = "inconclusive", "full_filter_mismatch"
        elif all(individual_nonempty) and all(prefix_nonempty[:-1]):
            status, reason = "plausible_valid_empty", "combination_empty"
        elif not all(individual_nonempty):
            status, reason = "predicate_empty", "single_condition_empty"
        else:
            status, reason = "inconclusive", "earlier_intersection_empty"
        return EmptyResultDiagnosis(
            status=status,
            reason_code=reason,
            predicate_count=len(predicates),
            individual_nonempty=individual_nonempty,
            prefix_nonempty=prefix_nonempty,
        )

    @classmethod
    def _split_and(cls, expression: exp.Expression) -> list[exp.Expression]:
        if isinstance(expression, exp.Paren):
            return cls._split_and(expression.this)
        if isinstance(expression, exp.And):
            return [*cls._split_and(expression.left), *cls._split_and(expression.right)]
        return [expression]

    @classmethod
    def _safe_predicate(
        cls,
        expression: exp.Expression,
        table_name: str,
        alias: str,
        allowed_columns: set[str],
    ) -> bool:
        if isinstance(expression, exp.Paren):
            return cls._safe_predicate(expression.this, table_name, alias, allowed_columns)
        if isinstance(expression, _COMPARISONS):
            return (
                cls._safe_column(expression.left, table_name, alias, allowed_columns)
                and cls._literal(expression.right)
            ) or (
                cls._literal(expression.left)
                and cls._safe_column(expression.right, table_name, alias, allowed_columns)
            )
        if isinstance(expression, exp.In):
            return (
                not expression.args.get("query")
                and 1 <= len(expression.expressions) <= 20
                and cls._safe_column(expression.this, table_name, alias, allowed_columns)
                and all(cls._literal(item) for item in expression.expressions)
            )
        if isinstance(expression, exp.Between):
            return (
                cls._safe_column(expression.this, table_name, alias, allowed_columns)
                and cls._literal(expression.args.get("low"))
                and cls._literal(expression.args.get("high"))
            )
        if isinstance(expression, exp.Not):
            return isinstance(expression.this, exp.Is) and cls._safe_predicate(
                expression.this, table_name, alias, allowed_columns
            )
        if isinstance(expression, exp.Is):
            return cls._safe_column(
                expression.left, table_name, alias, allowed_columns
            ) and isinstance(expression.right, (exp.Null, exp.Boolean))
        return False

    @staticmethod
    def _safe_column(
        expression: exp.Expression,
        table_name: str,
        alias: str,
        allowed_columns: set[str],
    ) -> bool:
        return (
            isinstance(expression, exp.Column)
            and expression.name in allowed_columns
            and expression.table in {"", table_name, alias}
            and not expression.db
            and not expression.catalog
        )

    @staticmethod
    def _literal(expression: exp.Expression | None) -> bool:
        return isinstance(expression, (exp.Literal, exp.Null, exp.Boolean)) or (
            isinstance(expression, exp.Neg) and isinstance(expression.this, exp.Literal)
        )

    @staticmethod
    def _outcome(status: str, reason_code: str, predicate_count: int = 0) -> EmptyResultDiagnosis:
        return EmptyResultDiagnosis(
            status=status, reason_code=reason_code, predicate_count=predicate_count
        )
