"""Label-aware Phase 9 metrics. Missing gold or telemetry is never scored as zero."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

import sqlglot
from sqlglot import exp

from app.schemas.query import QueryResponse

CRITIC_STAGES = {"query_plan_llm_review", "sql_llm_review", "result_llm_review"}


def _rows(value: object) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _recall(gold: set[Any], found: set[Any]) -> float | None:
    return round(len(gold & found) / len(gold), 4) if gold else None


def _join_key(left_table: str, left_column: str, right_table: str, right_column: str) -> tuple:
    return tuple(sorted(((left_table, left_column), (right_table, right_column))))


def _sql_gold(sql: object) -> tuple[set[str], set[tuple[str, str]], set[tuple]]:
    if not isinstance(sql, str) or not sql.strip():
        return set(), set(), set()
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except sqlglot.errors.ParseError:
        return set(), set(), set()
    ctes = {cte.alias for cte in tree.find_all(exp.CTE)}
    aliases = {
        table.alias_or_name: table.name
        for table in tree.find_all(exp.Table)
        if table.name not in ctes and table.db == "mart"
    }
    aliases.update({table: table for table in aliases.values()})
    tables = set(aliases.values())
    columns = {
        (aliases[column.table], column.name)
        for column in tree.find_all(exp.Column)
        if column.table in aliases and not isinstance(column.this, exp.Star)
    }
    joins: set[tuple] = set()
    for join in tree.find_all(exp.Join):
        on = join.args.get("on")
        if on is None:
            continue
        for equal in on.find_all(exp.EQ):
            left, right = equal.left, equal.right
            if (
                isinstance(left, exp.Column)
                and isinstance(right, exp.Column)
                and left.table in aliases
                and right.table in aliases
                and aliases[left.table] != aliases[right.table]
            ):
                joins.add(
                    _join_key(aliases[left.table], left.name, aliases[right.table], right.name)
                )
    return tables, columns, joins


def _coverage(expected: object, actual: object) -> float | None:
    if expected is None:
        return None
    if isinstance(expected, list):
        if not expected:
            return None
        actual_items = actual if isinstance(actual, list) else []
        return round(
            sum(any(_contains(item, candidate) for candidate in actual_items) for item in expected)
            / len(expected),
            4,
        )
    return float(_contains(expected, actual))


def _contains(expected: object, actual: object) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _contains(value, actual[key]) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and all(
            any(_contains(item, candidate) for candidate in actual) for item in expected
        )
    return expected == actual


def score_case_metrics(
    case: dict[str, Any],
    response: QueryResponse | None,
    *,
    retrieval: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    elapsed_ms: int,
    result_correct: bool | None = None,
) -> dict[str, Any]:
    """Return structured metrics without SQL, result rows, prompts or metadata bodies."""
    retrieval = retrieval if retrieval and retrieval.get("strategy") else {}
    runtime = runtime or {}
    events = events or []
    expected_plan = case.get("expected_query_plan") or {}
    if not isinstance(expected_plan, dict):
        expected_plan = {}
    actual_plan = (
        response.query_plan.model_dump(mode="json") if response and response.query_plan else {}
    )
    gold_tables, gold_columns, gold_joins = _sql_gold(case.get("expected_sql"))
    found_tables = {str(value) for value in retrieval.get("table_names") or []}
    found_columns = {
        (str(row.get("table_name")), str(row.get("column_name")))
        for row in _rows(retrieval.get("matched_columns"))
    }
    found_joins = {
        _join_key(
            str(row.get("left_table")),
            str(row.get("left_column")),
            str(row.get("right_table")),
            str(row.get("right_column")),
        )
        for row in _rows(retrieval.get("matched_join_relationships"))
    }
    metric_labels = expected_plan.get("metrics")
    gold_metrics = {
        str(code)
        for item in (metric_labels if isinstance(metric_labels, list) else [])
        if (code := item.get("metric_code") if isinstance(item, dict) else item)
        and isinstance(code, str)
    }
    actual_metrics = {
        str(row.get("metric_code"))
        for row in _rows(actual_plan.get("metrics"))
        if row.get("metric_code")
    }
    gold_filters = expected_plan.get("filters")
    actual_filters = actual_plan.get("filters") or []
    intent_accuracy = _coverage(expected_plan.get("intent"), actual_plan.get("intent"))
    metric_coverage = _recall(gold_metrics, actual_metrics)
    filter_coverage = _coverage(gold_filters, actual_filters)
    time_coverage = _coverage(expected_plan.get("time_range"), actual_plan.get("time_range"))
    grain_accuracy = _coverage(expected_plan.get("grain"), actual_plan.get("grain"))
    labeled_plan_scores = [
        value
        for value in (
            intent_accuracy,
            metric_coverage,
            filter_coverage,
            time_coverage,
            grain_accuracy,
        )
        if value is not None
    ]
    expected_status = case.get("expected_status")
    completed = bool(response and response.status == "completed")
    successful = completed and result_correct is True
    retry_count = response.retry_count if response else 0
    critic_events = [
        event
        for event in events
        if event.get("stage") in CRITIC_STAGES
        and event.get("status") != "running"
        and not str(event.get("type", "")).startswith("trace.")
    ]
    critic_calls = [
        event
        for event in events
        if event.get("type") == "trace.llm_call" and event.get("stage") in CRITIC_STAGES
    ]
    llm_events = [event for event in events if event.get("type") == "trace.llm_call"]
    context_events = [event for event in events if event.get("type") == "trace.context_selection"]

    def token_total(key: str) -> int | None:
        values = [(event.get("output") or {}).get(key) for event in llm_events]
        return sum(values) if values and all(isinstance(value, int) for value in values) else None

    def observed_or_runtime(key: str, observed: int | None) -> int | None:
        value = runtime.get(key)
        return value if isinstance(value, int) else observed

    context_values = [
        (event.get("output") or {}).get("context_tokens_estimated") for event in context_events
    ]
    critic_failed = any(event.get("status") == "failed" for event in critic_events)
    refresh_events = [
        event
        for event in events
        if event.get("stage") == "refresh_context" and event.get("status") != "running"
    ]
    critic_tokens = [event.get("output", {}).get("total_tokens") for event in critic_calls]
    critic_durations = [
        int(event["duration_ms"])
        for event in critic_events
        if isinstance(event.get("duration_ms"), int)
    ]
    return {
        "retrieval": {
            "table_recall_at_k": _recall(gold_tables, found_tables) if retrieval else None,
            "column_recall_at_k": _recall(gold_columns, found_columns) if retrieval else None,
            "metric_recall_at_k": _recall(
                gold_metrics, {str(value) for value in retrieval.get("metric_codes") or []}
            )
            if retrieval
            else None,
            "join_path_recall_at_k": _recall(gold_joins, found_joins) if retrieval else None,
            "retrieval_strategy": retrieval.get("strategy"),
            "configured_k": retrieval.get("configured_k"),
            "candidate_count": retrieval.get("candidate_count"),
        },
        "plan": {
            "semantic_accuracy": round(mean(labeled_plan_scores), 4)
            if labeled_plan_scores
            else None,
            "metric_coverage": metric_coverage,
            "filter_coverage": filter_coverage,
            "time_range_coverage": time_coverage,
            "grain_accuracy": grain_accuracy,
            "clarification_accuracy": float(
                (response.status == "needs_clarification")
                == (expected_status == "needs_clarification")
            )
            if response and expected_status in {"completed", "needs_clarification"}
            else None,
        },
        "runtime": {
            "first_pass_success": successful and retry_count == 0
            if result_correct is not None
            else None,
            "repair_success": successful
            if retry_count > 0 and result_correct is not None
            else None,
            "plan_repair_success": successful
            if runtime.get("plan_repairs_used", 0) > 0 and result_correct is not None
            else None,
            "sql_repair_success": successful
            if runtime.get("sql_repairs_used", 0) > 0 and result_correct is not None
            else None,
            "context_refresh_success": (
                completed
                and any(
                    event.get("status") == "passed"
                    and (event.get("output") or {}).get("expansion_status") == "expanded"
                    for event in refresh_events
                )
            )
            if refresh_events
            else None,
            "execution_retry_success": successful
            if runtime.get("execution_retries_used", 0) > 0 and result_correct is not None
            else None,
        },
        "cost": {
            "llm_calls": runtime.get("llm_calls", len(llm_events) if llm_events else None),
            "input_tokens": observed_or_runtime("prompt_tokens", token_total("prompt_tokens")),
            "output_tokens": observed_or_runtime(
                "completion_tokens", token_total("completion_tokens")
            ),
            "context_tokens_estimated": observed_or_runtime(
                "context_tokens_estimated",
                next((value for value in reversed(context_values) if isinstance(value, int)), None),
            ),
            "latency_ms": response.elapsed_ms or elapsed_ms if response else elapsed_ms,
        },
        "critic": {
            # End-result correctness cannot label a specific critic draft decision.
            "false_pass": None,
            "false_block": None,
            "repair_success_after_critic": successful
            if critic_failed and result_correct is not None
            else None,
            "token_overhead": sum(critic_tokens)
            if critic_tokens and all(isinstance(value, int) for value in critic_tokens)
            else None,
            "latency_overhead_ms": sum(critic_durations) if critic_durations else None,
        },
    }


def summarize_case_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate only observed labels; null means unavailable, not failure."""
    samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    for case in cases:
        for group, metrics in case.items():
            if not isinstance(metrics, dict):
                continue
            for name, value in metrics.items():
                if isinstance(value, bool | int | float):
                    samples[(group, name)].append(float(value))
    result: dict[str, Any] = {}
    for group in ("retrieval", "plan", "runtime", "cost", "critic"):
        keys = {key for case in cases for key in (case.get(group) or {})}
        result[group] = {
            key: round(mean(samples[group, key]), 4) if samples[group, key] else None
            for key in sorted(keys)
            if key != "retrieval_strategy"
        }
        result[group + "_samples"] = {
            key: len(samples[group, key]) for key in sorted(keys) if key != "retrieval_strategy"
        }
    latencies = sorted(samples["cost", "latency_ms"])
    for percentile, key in ((0.5, "p50_latency_ms"), (0.95, "p95_latency_ms")):
        rank = max(0, int(percentile * len(latencies) + 0.9999) - 1)
        result["cost"][key] = latencies[rank] if latencies else None
    return result
