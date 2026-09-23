"""Loss-limited compression of optional metadata descriptions."""

from typing import Any

_TEXT_LIMITS = {
    "table": {"description": 160},
    "column": {"description": 120},
    "metric": {"description": 180},
    "business_term": {"definition": 180},
    "join": {"description": 160},
    "rule": {"description": 180},
}


def compact_item(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Shorten prose/illustrations, never identifiers, formulas, or join keys."""
    result = dict(payload)
    if kind == "example" and result.get("expected_sql"):
        # A truncated SQL example is syntactically misleading; omit it instead.
        result.pop("expected_sql")
        result["example_sql_omitted"] = True
    for key, limit in _TEXT_LIMITS.get(kind, {}).items():
        value = result.get(key)
        if isinstance(value, str) and len(value) > limit:
            result[key] = value[:limit].rstrip() + "…"
    return result
