"""Deterministic Phase 10 case slices; absent labels are never guessed."""

from __future__ import annotations

from typing import Any

from sqlglot import exp, parse_one

SLICE_NAMES = (
    "single_table",
    "aggregation",
    "multi_table_join",
    "multi_time_window",
    "business_terminology",
    "ambiguous",
    "challenge",
)


def case_slices(case: dict[str, Any]) -> set[str]:
    tags = {str(tag).casefold() for tag in case.get("tags") or []}
    labels: set[str] = set()
    sql = case.get("expected_sql")
    if isinstance(sql, str) and sql.strip():
        try:
            parsed = parse_one(sql, read="postgres")
            tables = {table.name for table in parsed.find_all(exp.Table)
                      if table.db == "mart"}
            if len(tables) == 1:
                labels.add("single_table")
            if len(tables) > 1 and any(parsed.find_all(exp.Join)):
                labels.add("multi_table_join")
            if any(parsed.find_all(exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max)):
                labels.add("aggregation")
        except Exception:
            pass
    plan = case.get("expected_query_plan") or {}
    if isinstance(plan, dict):
        windows = {
            (str(metric["time_window"].get("start")), str(metric["time_window"].get("end")))
            for metric in plan.get("metrics", [])
            if isinstance(metric, dict) and isinstance(metric.get("time_window"), dict)
        }
        if len(windows) > 1 or "multi_time_window" in tags:
            labels.add("multi_time_window")
    def has_business_term(value: Any) -> bool:
        if isinstance(value, dict):
            if value.get("ref_type") == "business_term" or value.get("source") == "business_term":
                return True
            return any(has_business_term(item) for item in value.values())
        if isinstance(value, list):
            return any(has_business_term(item) for item in value)
        return False

    if (
        tags & {"business_term", "business_terminology", "术语", "业务术语"}
        or has_business_term(plan)
    ):
        labels.add("business_terminology")
    if case.get("expected_status") == "needs_clarification" or tags & {
        "ambiguous",
        "ambiguity",
        "歧义",
    }:
        labels.add("ambiguous")
    if "challenge" in str(case.get("source_type") or "") or any("challenge" in tag for tag in tags):
        labels.add("challenge")
    return labels


def summarize_slices(rows: list[dict[str, Any]]) -> dict[str, dict[str, float | int | None]]:
    """Each slice has its own denominator; one case may belong to several slices."""
    summary: dict[str, dict[str, float | int | None]] = {}
    for name in SLICE_NAMES:
        members = [row for row in rows if name in case_slices(row)]
        passed = sum(bool(row.get("passed")) for row in members)
        summary[name] = {
            "cases": len(members),
            "passed": passed,
            "accuracy": round(passed / len(members), 4) if members else None,
        }
    return summary
