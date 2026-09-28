"""Isolated, in-memory catalog overlay used only by candidate regression runs."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

_GROUP = {
    "metric": "metric", "term": "business_term", "join": "join",
    "example": "example", "rule": "rule",
}
_KEY = {
    "metric": "metric_code", "term": "term", "join": "id",
    "example": "id", "rule": "rule_code",
}


def overlay_rows(
    rows: dict[str, list[dict[str, Any]]], candidate: dict[str, Any] | None
) -> dict[str, list[dict[str, Any]]]:
    if not candidate or candidate.get("kind") not in _GROUP:
        return rows
    kind = str(candidate["kind"])
    group = _GROUP[kind]
    # Governance-only fields carry evaluation gold and must never enter retrieval context.
    value = {
        key: deepcopy(item)
        for key, item in dict(candidate["payload"]).items()
        if not key.startswith("_")
    }
    if kind in {"join", "example"} and candidate.get("action") == "create":
        value["id"] = str(candidate["candidate_id"])
    key = _KEY[kind]
    original = rows.get(group, [])
    rows[group] = [row for row in original if str(row.get(key)) != str(value.get(key))]
    rows[group].append(value)
    return rows
