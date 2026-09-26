"""Opt-in, advisory PostgreSQL EXPLAIN inspection; never runs ANALYZE."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Literal

import sqlglot
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlglot import exp

from app.db.session import engine as default_engine


@dataclass(frozen=True, slots=True)
class SQLPlanInspection:
    status: Literal["ok", "skipped", "failed"]
    reason_code: str
    node_count: int = 0
    root_plan_rows: int | None = None
    root_total_cost: float | None = None
    flags: list[str] = field(default_factory=list)

    def facts(self) -> dict[str, object]:
        return {
            "status": self.status,
            "reason_code": self.reason_code,
            "node_count": self.node_count,
            "root_plan_rows": self.root_plan_rows,
            "root_total_cost": self.root_total_cost,
            "flags": self.flags,
        }


class SQLPlanInspector:
    def __init__(
        self,
        *,
        engine: Engine | None = None,
        timeout_seconds: int = 3,
        max_plan_rows: int = 1_000_000,
        max_total_cost: int = 1_000_000,
    ) -> None:
        self.engine = engine or default_engine
        self.timeout_seconds = min(max(timeout_seconds, 1), 5)
        self.max_plan_rows = max(max_plan_rows, 1)
        self.max_total_cost = max(max_total_cost, 1)

    def inspect(self, sql: str) -> SQLPlanInspection:
        try:
            statements = [item for item in sqlglot.parse(sql, read="postgres") if item]
        except sqlglot.errors.ParseError:
            return SQLPlanInspection("skipped", "sql_parse_failed")
        if len(statements) != 1 or not isinstance(statements[0], exp.Select):
            return SQLPlanInspection("skipped", "select_only_required")
        expression = statements[0]
        if len(list(expression.find_all(exp.Table))) < 2 and not any(
            expression.find(node_type) for node_type in (exp.With, exp.Subquery)
        ):
            return SQLPlanInspection("skipped", "simple_sql")
        try:
            with self.engine.connect() as connection:
                transaction = connection.begin()
                try:
                    connection.execute(text("SET TRANSACTION READ ONLY"))
                    connection.execute(
                        text("select set_config('statement_timeout', :timeout, true)"),
                        {"timeout": f"{self.timeout_seconds * 1000}ms"},
                    )
                    payload = connection.execute(text("EXPLAIN (FORMAT JSON) " + sql)).scalar_one()
                    transaction.rollback()
                except Exception:
                    transaction.rollback()
                    raise
        except Exception:
            return SQLPlanInspection("failed", "explain_unavailable")
        try:
            document = json.loads(payload) if isinstance(payload, str) else payload
            root = document[0]["Plan"]
            if not isinstance(root, dict):
                raise ValueError("EXPLAIN plan root is not an object")
            return self._summarize(root)
        except (KeyError, IndexError, TypeError, ValueError):
            return SQLPlanInspection("failed", "invalid_plan_payload")

    def _summarize(self, root: dict[str, object]) -> SQLPlanInspection:
        flags: set[str] = set()
        nodes: list[dict[str, object]] = [root]
        count = 0
        while nodes and count < 256:
            node = nodes.pop()
            count += 1
            node_type = str(node.get("Node Type") or "")
            rows = self._number(node.get("Plan Rows"))
            if node_type in {"Seq Scan", "Parallel Seq Scan"} and rows is not None:
                if rows >= self.max_plan_rows:
                    flags.add("estimated_large_scan")
            children = [child for child in node.get("Plans", []) if isinstance(child, dict)]
            if node_type in {"Nested Loop", "Hash Join", "Merge Join"}:
                if rows is not None and rows >= self.max_plan_rows:
                    flags.add("estimated_large_join_output")
                if (
                    len(children) >= 2
                    and not any(node.get(key) for key in ("Join Filter", "Hash Cond", "Merge Cond"))
                    and not self._has_index_condition(children[1])
                ):
                    flags.add("possible_cartesian_join")
            nodes.extend(children)
        if nodes:
            flags.add("plan_node_limit_reached")
        total_cost = self._number(root.get("Total Cost"))
        if total_cost is not None and total_cost >= self.max_total_cost:
            flags.add("estimated_high_cost")
        root_rows = self._number(root.get("Plan Rows"))
        return SQLPlanInspection(
            status="ok",
            reason_code="plan_inspected",
            node_count=count,
            root_plan_rows=int(root_rows) if root_rows is not None else None,
            root_total_cost=total_cost,
            flags=sorted(flags),
        )

    @staticmethod
    def _has_index_condition(root: dict[str, object]) -> bool:
        pending = [root]
        visited = 0
        while pending and visited < 64:
            node = pending.pop()
            visited += 1
            if node.get("Index Cond") or node.get("Hash Cond") or node.get("Merge Cond"):
                return True
            pending.extend(child for child in node.get("Plans", []) if isinstance(child, dict))
        return False

    @staticmethod
    def _number(value: object) -> float | None:
        if isinstance(value, bool | str) or not isinstance(value, int | float):
            return None
        return float(value) if math.isfinite(value) else None
