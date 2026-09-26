"""Turn retrieved metadata into a bounded, replaceable prompt working set."""

from __future__ import annotations

import copy
import re
from typing import Any

from app.context.budget import ContextBudgetExceeded, estimate_context_tokens
from app.context.compactor import compact_item
from app.context.models import ContextBundle, ContextItem
from app.schemas.query_plan import QueryPlan

_FORMULA_COLUMN_RE = re.compile(
    r"\b(?:[A-Za-z][A-Za-z0-9_]*\.)?([A-Za-z][A-Za-z0-9_]*)\."
    r"([A-Za-z][A-Za-z0-9_]*)\b"
)
_GROUPS = {
    "metric": "metrics",
    "business_term": "business_terms",
    "join": "join_relationships",
    "example": "question_examples",
    "rule": "rule_constraints",
}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _identity(group: str, row: dict[str, Any]) -> str:
    if group == "tables":
        return f"{row.get('schema', 'mart')}.{row.get('name', '')}"
    if group == "metrics":
        return str(row.get("metric_code", ""))
    if group == "business_terms":
        return str(row.get("term", ""))
    if group == "join_relationships":
        return ":".join(str(row.get(key, "")) for key in (
            "left_table", "left_column", "right_table", "right_column"
        ))
    if group == "question_examples":
        return str(row.get("id") or row.get("question", ""))
    return str(row.get("rule_code") or row.get("id") or row.get("rule_name", ""))


def merge_contexts(base: dict[str, Any], addition: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Merge targeted evidence without making context append-only or duplicating rows."""
    merged = copy.deepcopy(base)
    for key in ("prompt_context", "context_stats", "context_bundle", "retrieval_trace"):
        merged.pop(key, None)
    duplicates = 0
    for group in ("tables", "metrics", "business_terms", "join_relationships",
                  "question_examples", "rule_constraints"):
        existing = {_identity(group, row): row for row in _rows(merged.get(group))}
        for row in _rows(addition.get(group)):
            key = _identity(group, row)
            if key in existing:
                duplicates += 1
                if group == "tables":
                    known = {col.get("name") for col in _rows(existing[key].get("columns"))}
                    for column in _rows(row.get("columns")):
                        if column.get("name") not in known:
                            existing[key].setdefault("columns", []).append(column)
                            known.add(column.get("name"))
                        else:
                            duplicates += 1
                continue
            existing[key] = copy.deepcopy(row)
        merged[group] = list(existing.values())
    for key in ("table_allowlist", "sensitive_columns"):
        merged[key] = list(dict.fromkeys([*(merged.get(key) or []), *(addition.get(key) or [])]))
    # Each database load supplies a complete physical JOIN catalog. Replace the
    # old policy snapshot instead of merging retrieval-limited JOIN evidence.
    if "join_relationship_allowlist" in addition:
        merged["join_relationship_allowlist"] = copy.deepcopy(
            addition["join_relationship_allowlist"]
        )
    allowed = dict(merged.get("allowed_columns_by_table") or {})
    for table, columns in (addition.get("allowed_columns_by_table") or {}).items():
        allowed[table] = list(dict.fromkeys([*(allowed.get(table) or []), *columns]))
    merged["allowed_columns_by_table"] = allowed
    source_retrieval = dict(merged.get("retrieval") or {})
    extra_retrieval = addition.get("retrieval") or {}
    for key in ("evidence", "matched_columns"):
        old_rows = _rows(source_retrieval.get(key))
        seen = {str(row.get("doc_id") or row) for row in old_rows}
        for row in _rows(extra_retrieval.get(key)):
            marker = str(row.get("doc_id") or row)
            if marker not in seen:
                old_rows.append(row)
                seen.add(marker)
            else:
                duplicates += 1
        source_retrieval[key] = old_rows
    source_retrieval["keywords"] = list(dict.fromkeys([
        *(source_retrieval.get("keywords") or []), *(extra_retrieval.get("keywords") or [])
    ]))
    merged["retrieval"] = source_retrieval
    merged["table_count"] = len(merged["tables"])
    merged["metric_count"] = len(merged["metrics"])
    return merged, duplicates


class ContextBuilder:
    def __init__(self, budget: int) -> None:
        if budget < 512:
            raise ValueError("schema_context_budget must be at least 512 estimated tokens")
        self.budget = budget

    def build(
        self,
        raw: dict[str, Any],
        question: str | None,
        query_plan: QueryPlan | None = None,
        *,
        pinned_ids: set[str] | None = None,
        expansion_count: int = 0,
        dedup_count: int = 0,
    ) -> ContextBundle:
        retrieval = raw.get("retrieval") if isinstance(raw.get("retrieval"), dict) else {}
        contract = raw.get("semantic_contract") or {}
        view: dict[str, Any] = {
            "version": raw.get("version", "1.0"),
            "source": raw.get("source"),
            "query_intent": raw.get("query_intent"),
            "scenario": raw.get("scenario"),
            "retrieval": {
                "strategy": retrieval.get("strategy"),
                "keywords": list(retrieval.get("keywords") or [])[:12],
            },
            "tables": [],
            "table_count": 0,
            "metrics": [],
            "metric_count": 0,
            "business_terms": [],
            "join_relationships": [],
            "question_examples": [],
            "rule_constraints": [],
            "table_allowlist": [],
            "sensitive_columns": list(raw.get("sensitive_columns") or []),
            "semantic_contract": {
                "rules": list(contract.get("rules") or []),
                "metric_formulas": {},
                "metric_output_aliases": contract.get("metric_output_aliases") or {},
                "reference_date": contract.get("reference_date"),
            },
            "notes": list(raw.get("notes") or []),
        }
        if estimate_context_tokens(view) > self.budget:
            raise ContextBudgetExceeded("Fixed semantic contract exceeds schema_context_budget")
        items, extracted_duplicates = self._candidates(
            raw, question or "", query_plan, pinned_ids or set()
        )
        dedup_count += extracted_duplicates
        selected: list[str] = []
        evicted = compacted = 0
        # A table must precede its columns.  The few table headers are cheap; item
        # priority still controls all fields, metrics, examples and rules thereafter.
        tables = sorted((item for item in items if item.kind == "table"),
                        key=lambda item: (-item.required, -item.priority, item.doc_id))
        others = sorted((item for item in items if item.kind != "table"),
                        key=lambda item: (-item.required, -item.priority, item.doc_id))
        for item in [*tables, *others]:
            if item.parent_table and item.parent_table not in view["table_allowlist"]:
                if item.required:
                    raise ContextBudgetExceeded(
                        f"Required column's table was not retained: {item.doc_id}"
                    )
                evicted += 1
                continue
            full = self._with_item(view, item, item.payload)
            if estimate_context_tokens(full) <= self.budget:
                view = full
                selected.append(item.doc_id)
                continue
            shortened = compact_item(item.kind, item.payload)
            if shortened != item.payload:
                compact_view = self._with_item(view, item, shortened)
                if estimate_context_tokens(compact_view) <= self.budget:
                    view = compact_view
                    selected.append(item.doc_id)
                    compacted += 1
                    continue
            if item.required:
                raise ContextBudgetExceeded(f"Required evidence exceeds budget: {item.doc_id}")
            evicted += 1
        return ContextBundle(
            prompt_context=view,
            budget=self.budget,
            token_usage=estimate_context_tokens(view),
            item_ids=selected,
            retrieval_trace=_rows(retrieval.get("evidence")),
            context_expansion_count=expansion_count,
            dedup_count=dedup_count,
            eviction_count=evicted,
            compaction_count=compacted,
        )

    @staticmethod
    def _with_item(
        view: dict[str, Any], item: ContextItem, payload: dict[str, Any]
    ) -> dict[str, Any]:
        result = copy.deepcopy(view)
        if item.kind == "table":
            result["tables"].append({**payload, "columns": []})
            result["table_allowlist"].append(payload["name"])
            result["table_count"] = len(result["tables"])
        elif item.kind == "column":
            table = next(row for row in result["tables"] if row["name"] == item.parent_table)
            table["columns"].append(payload)
        else:
            result[_GROUPS[item.kind]].append(payload)
            if item.kind == "metric" and payload.get("formula"):
                result["semantic_contract"]["metric_formulas"][payload["metric_code"]] = (
                    payload["formula"]
                )
            if item.kind == "metric":
                result["metric_count"] = len(result["metrics"])
        return result

    @staticmethod
    def _candidates(
        raw: dict[str, Any], question: str, query_plan: QueryPlan | None,
        pinned_ids: set[str],
    ) -> tuple[list[ContextItem], int]:
        retrieval = raw.get("retrieval") or {}
        analysis = retrieval.get("query_analysis") or {}
        intent = analysis.get("intent_hint") if isinstance(analysis, dict) else None
        domains = set(analysis.get("domains") or []) if isinstance(analysis, dict) else set()
        evidence = {
            str(row["doc_id"]): index
            for index, row in enumerate(_rows(retrieval.get("evidence")))
            if row.get("doc_id")
        }
        matched_columns = {
            (row.get("table_name"), row.get("column_name"))
            for row in _rows(retrieval.get("matched_columns"))
        }
        plan_tables = set(query_plan.data_requirements.candidate_tables) if query_plan else set()
        plan_joins = query_plan.data_requirements.required_join_paths if query_plan else []
        plan_metrics = (
            {metric.metric_code for metric in query_plan.metrics if metric.metric_code}
            if query_plan else set()
        )
        plan_fields: set[str] = set()
        if query_plan:
            if query_plan.grain:
                plan_fields.update(value for value in query_plan.grain.keys if value)
            plan_fields.update(value for value in query_plan.output.columns if value)
            plan_fields.update(
                item.dimension_code for item in query_plan.dimensions if item.dimension_code
            )
            plan_fields.update(item.field_code for item in query_plan.filters if item.field_code)
            plan_fields.update(item.field_code for item in query_plan.order_by if item.field_code)
            for metric in query_plan.metrics:
                plan_fields.update(item.field_code for item in metric.filters if item.field_code)
        formulas = [
            row.get("formula", "") for row in _rows(raw.get("metrics"))
            if row.get("metric_code") in plan_metrics
        ]
        formula_fields = set().union(*(
            {f"{table}.{column}" for table, column in _FORMULA_COLUMN_RE.findall(str(formula))}
            for formula in formulas
        )) if formulas else set()
        joined_fields = {
            f"{row[side + '_table']}.{row[side + '_column']}"
            for row in _rows(raw.get("join_relationships"))
            for side in ("left", "right")
            if row.get(side + "_table") and row.get(side + "_column")
        }
        required_fields = plan_fields | formula_fields | joined_fields
        required_tables = plan_tables | {
            field.split(".", 1)[0] for field in required_fields if "." in field
        }
        required_tables.update(
            str(table)
            for row in _rows(raw.get("metrics"))
            if row.get("metric_code") in plan_metrics
            for table in row.get("source_tables") or []
        )
        lower_question = question.lower()
        items: list[ContextItem] = []
        seen: set[str] = set()
        duplicates = 0

        def add(doc_id: str, kind: str, payload: dict[str, Any], base: float,
                required: bool = False, parent: str | None = None) -> None:
            nonlocal duplicates
            if doc_id in seen:
                duplicates += 1
                return
            seen.add(doc_id)
            rank = evidence.get(doc_id)
            priority = base + (30 / (rank + 1) if rank is not None else 0)
            if intent == "join_lookup" and kind in {"join", "column"}:
                priority += 30 if kind == "join" else 12
            elif intent == "aggregation" and kind == "metric":
                priority += 25
            elif intent == "detail_query" and kind == "column":
                priority += 20
            if kind == "table" and payload.get("domain") in domains:
                priority += 15
            title = str(payload.get("display_name") or payload.get("metric_name") or
                        payload.get("term") or payload.get("name") or "").lower()
            if title and title in lower_question:
                priority += 20
            items.append(ContextItem(doc_id, kind, payload, priority,
                                     required or doc_id in pinned_ids, parent))

        raw_tables = _rows(raw.get("tables"))
        first_table = str(raw_tables[0].get("name")) if raw_tables else None
        for table in raw_tables:
            name = str(table.get("name", ""))
            schema = str(table.get("schema", "mart"))
            add(f"table:{schema}.{name}", "table", {key: value for key, value in table.items()
                if key != "columns"}, 75,
                required=name in required_tables or (not required_tables and name == first_table))
            for column in _rows(table.get("columns")):
                col = str(column.get("name", ""))
                field_id = f"{name}.{col}"
                field_required = col in required_fields or field_id in required_fields
                matched = (name, col) in matched_columns
                add(f"column:{schema}.{name}.{col}", "column", column,
                    62 + (35 if matched else 0) + (15 if field_required else 0),
                    required=field_required, parent=name)
        for row in _rows(raw.get("metrics")):
            code = str(row.get("metric_code", ""))
            add(f"metric:{code}", "metric", row, 105,
                required=code in plan_metrics)
        for row in _rows(raw.get("business_terms")):
            term = str(row.get("term", ""))
            add(f"term:{term}", "business_term", row, 90,
                required=bool(term and term.lower() in lower_question))
        for row in _rows(raw.get("join_relationships")):
            left, right = str(row.get("left_table", "")), str(row.get("right_table", ""))
            identifier = row.get("id") or _identity("join_relationships", row)
            add(f"join:{identifier}", "join", row, 100,
                required=bool(
                    (plan_tables and left in plan_tables and right in plan_tables)
                    or any(left in path and right in path for path in plan_joins)
                ))
        for row in _rows(raw.get("question_examples")):
            identifier = row.get("id") or row.get("question", "")
            add(f"example:{identifier}", "example", row, 35)
        for row in _rows(raw.get("rule_constraints")):
            identifier = row.get("rule_code") or row.get("id") or row.get("rule_name", "")
            add(f"rule:{identifier}", "rule", row, 82,
                required=str(row.get("severity", "")).lower() in {"critical", "high", "block"})
        return items, duplicates
